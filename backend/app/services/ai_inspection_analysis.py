"""
AI analysis of inspector-submitted evidence: per-photo theme
detection + parameter scoring, aggregation into an inspection-level
report, and comparison against a project's previous inspection.

--- The theme system -------------------------------------------------
A single "cleanliness score" for a whole site visit is close to
meaningless -- a photo of a washroom and a photo of a cracked
retaining wall are evidence of completely different things. Instead,
every photo is first classified into one theme from a fixed taxonomy
(THEME_RULES below), and each theme declares WHICH quality parameters
it's actually evidence for, and how strongly:

    restroom  -> mostly cleanliness/hygiene, a little infrastructure
    structural_damage -> mostly infrastructure/safety, nothing about hygiene
    exterior_campus -> maintenance/aesthetics/safety

A photo only ever contributes scores to the parameters its theme
declares -- a washroom photo never affects the "aesthetics" score, a
playground photo never affects "hygiene". This is what lets the
inspection-level report end up with six independently meaningful
point scores instead of one mushy average.

--- Two analysis backends --------------------------------------------
1. Offline heuristic (always available, zero configuration): theme is
   guessed from the inspector's caption/report text via keyword
   matching, and parameter scores are derived from real pixel
   statistics (brightness, sharpness, edge density, dark/stain ratio)
   computed with OpenCV -- the same "no network, no API key" approach
   as app/services/ai_vision.py's face-check.
2. Hosted vision-language API (optional, see app/services/vision_api_client.py
   and app/config.py): if any provider key is configured, the actual
   photo content drives theme detection + scoring instead of just the
   caption text. Falls back to (1) automatically on any failure.

Every photo is analyzed through whichever backend is available at
upload time (see POST /inspections/{id}/evidence/upload); aggregation
into an inspection-level InspectionAnalysisReport happens once, at
report-submission time (see POST /inspections/{id}/submit-report).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from app.config import settings
from app.services import vision_api_client
from app.services.ai_vision import InvalidImageError

PARAMETERS = ("cleanliness", "hygiene", "infrastructure", "safety", "maintenance", "aesthetics")

PARAMETER_LABELS = {
    "cleanliness": "Cleanliness",
    "hygiene": "Hygiene & Sanitation",
    "infrastructure": "Infrastructure Condition",
    "safety": "Safety",
    "maintenance": "Maintenance & Upkeep",
    "aesthetics": "Aesthetics & Presentation",
}

# --- Theme taxonomy ---------------------------------------------------
# `weights` must sum to 1.0 -- they control both which parameters a
# photo of this theme contributes to, and how strongly (see
# _blend_toward_neutral below: a low-weight parameter for a given
# theme is pulled toward a neutral baseline rather than swinging on
# full pixel-derived signal, since a washroom photo is only weak
# evidence about "infrastructure" in the structural sense).
THEME_RULES: dict[str, dict] = {
    "restroom": {
        "label": "Restroom / Sanitation Block",
        "keywords": ["bathroom", "toilet", "washroom", "restroom", "urinal", "latrine", "loo", "lavatory"],
        "weights": {"cleanliness": 0.4, "hygiene": 0.4, "infrastructure": 0.2},
    },
    "kitchen_dining": {
        "label": "Kitchen / Dining / Mess Hall",
        "keywords": ["kitchen", "dining", "mess hall", "mess", "canteen", "pantry", "cooking", "cafeteria"],
        "weights": {"cleanliness": 0.35, "hygiene": 0.4, "infrastructure": 0.25},
    },
    "classroom_office": {
        "label": "Classroom / Office / Interior Hall",
        "keywords": ["classroom", "class room", "lecture", "office", "desk", "blackboard", "whiteboard", "workshop"],
        "weights": {"cleanliness": 0.3, "infrastructure": 0.4, "aesthetics": 0.3},
    },
    "dormitory": {
        "label": "Dormitory / Residential Room",
        "keywords": ["dormitory", "dorm", "hostel room", "bedroom", "bunk", "residential"],
        "weights": {"cleanliness": 0.4, "infrastructure": 0.35, "hygiene": 0.25},
    },
    "corridor_common": {
        "label": "Corridor / Staircase / Common Area",
        "keywords": ["corridor", "hallway", "passage", "lobby", "staircase", "stairs", "common area", "entrance"],
        "weights": {"cleanliness": 0.3, "infrastructure": 0.4, "safety": 0.3},
    },
    "structural_damage": {
        "label": "Structural Damage / Disrepair",
        "keywords": ["crack", "cracked", "broken wall", "damage", "damaged", "collapse", "collapsed",
                     "leak", "leakage", "seepage", "damp", "dampness", "ceiling fall", "plaster", "pothole"],
        "weights": {"infrastructure": 0.6, "safety": 0.4},
    },
    "electrical": {
        "label": "Electrical Installation",
        "keywords": ["wiring", "electrical", "switchboard", "panel", "exposed wire", "transformer", "meter box"],
        "weights": {"safety": 0.65, "infrastructure": 0.35},
    },
    "water_drainage": {
        "label": "Water Supply / Drainage / Sanitation Infrastructure",
        "keywords": ["drain", "drainage", "sewage", "water tank", "overflow", "stagnant water", "borewell", "pipeline"],
        "weights": {"hygiene": 0.4, "infrastructure": 0.35, "safety": 0.25},
    },
    "fire_safety": {
        "label": "Fire / Emergency Safety Equipment",
        "keywords": ["fire extinguisher", "fire exit", "smoke detector", "emergency exit", "fire alarm", "hydrant"],
        "weights": {"safety": 1.0},
    },
    "exterior_campus": {
        "label": "Exterior / Campus / Grounds",
        "keywords": ["playground", "campus", "garden", "exterior", "facade", "compound", "ground", "parking", "boundary wall"],
        "weights": {"maintenance": 0.4, "aesthetics": 0.3, "safety": 0.3},
    },
    "general": {
        "label": "General Site View",
        "keywords": [],
        "weights": {"cleanliness": 0.5, "infrastructure": 0.5},
    },
}

# Checked in keyword-count order (excluding "general", which is the
# fallback when nothing else matches at all).
_THEME_KEYS_FOR_MATCHING = [k for k in THEME_RULES if k != "general"]

_POSITIVE_WORDS = [
    "excellent", "clean", "well maintained", "well-maintained", "satisfactory", "good condition",
    "hygienic", "tidy", "spotless", "functional", "safe", "adequate", "improved", "renovated",
]
_NEGATIVE_WORDS = [
    "broken", "leak", "leaking", "unhygienic", "poor", "damaged", "overflowing", "infested",
    "unsafe", "filthy", "dirty", "cracked", "collapsed", "neglected", "unusable", "hazard", "hazardous",
    "damp", "mold", "mould", "stagnant", "garbage", "unclean",
]


def _keyword_theme_scores(text: str) -> dict[str, int]:
    text = text.lower()
    scores = {}
    for key in _THEME_KEYS_FOR_MATCHING:
        hits = sum(text.count(kw) for kw in THEME_RULES[key]["keywords"])
        if hits:
            scores[key] = hits
    return scores


def detect_theme_from_text(caption: str | None, extra_text: str = "") -> tuple[str, float]:
    """Keyword match against a photo's caption (and, weakly, the
    surrounding report text) to guess its theme. This is the whole
    theme-detection mechanism in the offline path, and is used as a
    prior/fallback even when a hosted vision API is configured."""
    combined = f"{caption or ''} {extra_text or ''}".strip()
    if not combined:
        return "general", 0.25
    scores = _keyword_theme_scores(combined)
    if not scores:
        return "general", 0.3
    best_key = max(scores, key=scores.get)
    hits = scores[best_key]
    confidence = min(0.95, 0.5 + 0.15 * hits)
    return best_key, confidence


@dataclass
class PhotoAnalysis:
    theme: str
    theme_label: str
    confidence: float
    scores: dict[str, float]  # only the parameters this theme applies to
    findings: list[str]
    quality_flags: dict[str, bool]
    source: str  # "vision_api" | "heuristic" | "heuristic_no_image"


def _decode_image(image_bytes: bytes):
    if not image_bytes:
        raise InvalidImageError("Empty image")
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError("Could not decode image data")
    height, width = image.shape[:2]
    longest_edge = max(height, width)
    max_dim = 1200
    if longest_edge > max_dim:
        scale = max_dim / longest_edge
        image = cv2.resize(
            image, (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return image


def _pixel_metrics(image_bgr) -> dict[str, float]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 100, 200)
    edge_density = float(edges.mean()) / 255.0
    saturation = float(hsv[:, :, 1].mean())
    dark_ratio = float((gray < 70).mean())

    return {
        "brightness": brightness,
        "sharpness": sharpness,
        "edge_density": edge_density,
        "saturation": saturation,
        "dark_ratio": dark_ratio,
    }


def _quality_flags(metrics: dict[str, float]) -> dict[str, bool]:
    return {
        "blurry": metrics["sharpness"] < 40,
        "too_dark": metrics["brightness"] < 45,
        "overexposed": metrics["brightness"] > 235,
    }


def _clamp(value: float, low: float = 3.0, high: float = 98.0) -> float:
    return max(low, min(high, value))


def _raw_parameter_scores(metrics: dict[str, float]) -> dict[str, float]:
    """Deterministic, pixel-stat-driven proxy scores for every
    parameter, before theme-weighting is applied. Not a substitute for
    a trained damage/cleanliness classifier -- a documented,
    explainable heuristic that reacts sensibly to real image content:
    more dark/stained area and more visual clutter/irregularity pulls
    every score down; a bright, low-clutter, uniform frame scores
    higher. See module docstring for when the hosted vision-API path
    (real scene understanding) is used instead."""
    dark = metrics["dark_ratio"] * 100
    edge = metrics["edge_density"] * 100
    sat_penalty = abs(metrics["saturation"] - 105) * 0.1  # very washed-out or very oversaturated framing

    return {
        "cleanliness": _clamp(93 - dark * 0.9 - edge * 0.30),
        "hygiene": _clamp(91 - dark * 1.05 - edge * 0.15),
        "infrastructure": _clamp(90 - edge * 0.5 - dark * 0.25),
        "safety": _clamp(88 - edge * 0.35 - dark * 0.35),
        "maintenance": _clamp(89 - edge * 0.45 - dark * 0.30),
        "aesthetics": _clamp(86 - edge * 0.4 - sat_penalty),
    }


def _findings_from_metrics(metrics: dict[str, float], flags: dict[str, bool]) -> list[str]:
    findings = []
    if metrics["dark_ratio"] > 0.22:
        findings.append("Noticeable dark or stained patches visible in the frame")
    if metrics["edge_density"] > 0.16:
        findings.append("High visual clutter or surface irregularity detected")
    if flags["blurry"]:
        findings.append("Photo is somewhat blurry — fine detail may be under-assessed")
    if flags["too_dark"]:
        findings.append("Photo was taken in low light — scoring confidence is reduced")
    if flags["overexposed"]:
        findings.append("Photo is overexposed / washed out — scoring confidence is reduced")
    if not findings:
        findings.append("No significant visual issues flagged in this photo")
    return findings


def _weighted_theme_scores(raw: dict[str, float], weights: dict[str, float]) -> dict[str, float]:
    """Applies theme weighting: a parameter this theme cares strongly
    about (weight close to 1) keeps close to its raw pixel-derived
    score; a parameter it only weakly implies is pulled toward a
    neutral 70 baseline, since a single photo is thin evidence for a
    parameter its theme doesn't centrally concern."""
    out = {}
    for param, weight in weights.items():
        raw_score = raw[param]
        out[param] = round(raw_score * weight + 70 * (1 - weight), 1)
    return out


def analyze_photo(
    image_bytes: bytes,
    caption: str | None = None,
    context_text: str = "",
    media_type: str = "image/jpeg",
) -> PhotoAnalysis:
    """Runs full analysis on one uploaded evidence photo. Raises
    InvalidImageError if the bytes can't be decoded as an image (the
    route layer turns that into a 400)."""
    image = _decode_image(image_bytes)
    metrics = _pixel_metrics(image)
    flags = _quality_flags(metrics)

    api_result = None
    try:
        api_result = vision_api_client.classify_and_score(
            image_bytes, media_type, caption, THEME_RULES
        )
    except Exception:
        api_result = None  # belt-and-braces -- classify_and_score already swallows its own errors

    if api_result is not None:
        theme_key = api_result.theme
        confidence = api_result.confidence
        scores = api_result.parameters
        findings = api_result.findings or _findings_from_metrics(metrics, flags)
        source = "vision_api"
    else:
        theme_key, confidence = detect_theme_from_text(caption, context_text)
        raw = _raw_parameter_scores(metrics)
        scores = _weighted_theme_scores(raw, THEME_RULES[theme_key]["weights"])
        findings = _findings_from_metrics(metrics, flags)
        source = "heuristic"

    return PhotoAnalysis(
        theme=theme_key,
        theme_label=THEME_RULES[theme_key]["label"],
        confidence=round(confidence, 2),
        scores=scores,
        findings=findings,
        quality_flags=flags,
        source=source,
    )


# --- Aggregation: per-photo analyses -> one inspection-level report ---

_GRADE_BANDS = [
    (90, "Excellent"),
    (75, "Good"),
    (60, "Satisfactory"),
    (40, "Needs Improvement"),
    (0, "Critical"),
]


def _grade_for(score: float) -> str:
    for threshold, label in _GRADE_BANDS:
        if score >= threshold:
            return label
    return "Critical"


def _text_sentiment_nudge(report_text: str) -> float:
    text = (report_text or "").lower()
    pos = sum(text.count(w) for w in _POSITIVE_WORDS)
    neg = sum(text.count(w) for w in _NEGATIVE_WORDS)
    return max(-10.0, min(10.0, (pos - neg) * 2.5))


@dataclass
class AggregatedAnalysis:
    overall_score: float
    grade: str
    parameter_scores: dict[str, float | None]
    parameter_evidence_counts: dict[str, int]
    summary: str
    theme_breakdown: list[dict]
    source: str  # "vision_api" | "heuristic" | "text_only" | "hybrid"


def aggregate_analysis(
    photo_records: list[tuple[str, PhotoAnalysis]],  # (evidence_id, analysis)
    report_text: str,
) -> AggregatedAnalysis:
    """Rolls up every submitted photo's analysis into one
    inspection-level report. `photo_records` may be empty (a
    text-only report) -- handled explicitly below rather than crashing
    on an empty aggregation."""
    nudge = _text_sentiment_nudge(report_text)
    sources_used = {a.source for _id, a in photo_records}

    param_totals: dict[str, float] = {p: 0.0 for p in PARAMETERS}
    param_weights: dict[str, float] = {p: 0.0 for p in PARAMETERS}
    param_counts: dict[str, int] = {p: 0 for p in PARAMETERS}
    theme_breakdown: list[dict] = []

    for evidence_id, analysis in photo_records:
        theme_breakdown.append({
            "evidence_id": evidence_id,
            "theme": analysis.theme,
            "theme_label": analysis.theme_label,
            "confidence": analysis.confidence,
            "scores": analysis.scores,
            "findings": analysis.findings,
            "quality_flags": analysis.quality_flags,
            "source": analysis.source,
        })
        for param, score in analysis.scores.items():
            weight = analysis.confidence
            param_totals[param] += score * weight
            param_weights[param] += weight
            param_counts[param] += 1

    parameter_scores: dict[str, float | None] = {}
    for param in PARAMETERS:
        if param_weights[param] > 0:
            base = param_totals[param] / param_weights[param]
            parameter_scores[param] = round(_clamp(base + nudge), 1)
        else:
            parameter_scores[param] = None

    assessed = {p: s for p, s in parameter_scores.items() if s is not None}

    if not photo_records:
        # Text-only report: no photographic evidence at all. Every
        # parameter gets a single neutral baseline nudged by the
        # inspector's own wording, clearly flagged as low-confidence
        # rather than silently presented as equivalent to a
        # photo-backed score.
        baseline = round(_clamp(65 + nudge), 1)
        parameter_scores = {p: baseline for p in PARAMETERS}
        assessed = dict(parameter_scores)
        source = "text_only"
        overall_score = baseline
    elif assessed:
        weight_sum = sum(param_counts[p] for p in assessed) or 1
        overall_score = round(
            sum(assessed[p] * param_counts[p] for p in assessed) / weight_sum, 1
        )
        source = "vision_api" if sources_used == {"vision_api"} else (
            "heuristic" if sources_used == {"heuristic"} else "hybrid"
        )
    else:
        overall_score = round(_clamp(65 + nudge), 1)
        source = "heuristic"

    grade = _grade_for(overall_score)
    summary = _build_summary(
        photo_records=photo_records, parameter_scores=parameter_scores,
        param_counts=param_counts, overall_score=overall_score, grade=grade,
        nudge=nudge, theme_breakdown=theme_breakdown,
    )

    return AggregatedAnalysis(
        overall_score=overall_score,
        grade=grade,
        parameter_scores=parameter_scores,
        parameter_evidence_counts=param_counts,
        summary=summary,
        theme_breakdown=theme_breakdown,
        source=source,
    )


def _build_summary(
    photo_records, parameter_scores, param_counts, overall_score, grade, nudge, theme_breakdown,
) -> str:
    lines = []

    if not photo_records:
        lines.append(
            "No photographic evidence was submitted with this report. The scores below "
            "are derived solely from the inspector's written notes and should be treated "
            "as low-confidence until photo evidence is provided."
        )
    else:
        themes_seen = sorted({rec["theme_label"] for rec in theme_breakdown})
        lines.append(
            f"This inspection is based on {len(photo_records)} submitted photo"
            f"{'s' if len(photo_records) != 1 else ''} covering: {', '.join(themes_seen)}. "
            f"Overall condition rates {overall_score:.0f}/100 ({grade})."
        )

    for param in PARAMETERS:
        score = parameter_scores.get(param)
        if score is None:
            continue
        count = param_counts.get(param, 0)
        basis = f"{count} photo{'s' if count != 1 else ''}" if count else "written notes only"
        lines.append(
            f"{PARAMETER_LABELS[param]}: {score:.0f}/100 ({_grade_for(score)}), based on {basis}."
        )

    # Surface the most useful concrete findings: pull from the lowest-
    # scoring photo(s) so the summary points at something specific
    # rather than only reciting numbers.
    if theme_breakdown:
        worst = sorted(
            theme_breakdown,
            key=lambda rec: min(rec["scores"].values()) if rec["scores"] else 100,
        )[:2]
        for rec in worst:
            if rec["findings"]:
                lines.append(f"[{rec['theme_label']}] {rec['findings'][0]}")

    if abs(nudge) >= 3:
        direction = "upward" if nudge > 0 else "downward"
        lines.append(
            f"Scores were adjusted slightly {direction} based on the tone of the inspector's written report."
        )

    if grade == "Critical":
        lines.append("Recommendation: urgent remedial action is advised before the next scheduled visit.")
    elif grade == "Needs Improvement":
        lines.append("Recommendation: corrective action should be planned and verified at the next inspection.")
    elif grade == "Satisfactory":
        lines.append("Recommendation: condition is acceptable but has room for improvement.")
    else:
        lines.append("Recommendation: maintain current standards.")

    return " ".join(lines)


# --- Comparison against the previous inspection at the same project ---

_TREND_BAND = 5.0  # |delta| below this is "stable", not noise-chasing every 1-2 point wobble


def _trend(delta: float) -> str:
    if delta >= _TREND_BAND:
        return "improved"
    if delta <= -_TREND_BAND:
        return "declined"
    return "stable"


def compare_analyses(
    current_scores: dict[str, float | None],
    current_overall: float,
    previous_scores: dict[str, float | None],
    previous_overall: float,
    previous_date: datetime | None,
) -> tuple[dict, str, str]:
    """Returns (comparison_deltas, comparison_summary, overall_trend)."""
    deltas: dict[str, dict] = {}
    for param in PARAMETERS:
        cur = current_scores.get(param)
        prev = previous_scores.get(param)
        if cur is not None and prev is not None:
            delta = round(cur - prev, 1)
            deltas[param] = {"previous": prev, "current": cur, "delta": delta, "trend": _trend(delta)}
        elif cur is not None and prev is None:
            deltas[param] = {"previous": None, "current": cur, "delta": None, "trend": "newly_assessed"}
        elif cur is None and prev is not None:
            deltas[param] = {"previous": prev, "current": None, "delta": None, "trend": "not_assessed_this_time"}
        # both None -> parameter never assessed either time, omit entirely

    overall_delta = round(current_overall - previous_overall, 1)
    overall_trend = _trend(overall_delta)

    when = previous_date.strftime("%d %b %Y") if previous_date else "the previous inspection"
    lines = [
        f"Compared to the inspection on {when} (overall {previous_overall:.0f} → {current_overall:.0f}, "
        f"{'+' if overall_delta >= 0 else ''}{overall_delta:.0f} pts): "
        f"condition has {overall_trend} overall."
    ]

    changed = {
        p: d for p, d in deltas.items()
        if d.get("delta") is not None and abs(d["delta"]) >= _TREND_BAND
    }
    for param, d in sorted(changed.items(), key=lambda kv: abs(kv[1]["delta"]), reverse=True):
        verb = "improved" if d["trend"] == "improved" else "declined"
        lines.append(
            f"{PARAMETER_LABELS[param]} {verb} from {d['previous']:.0f} to {d['current']:.0f} "
            f"({'+' if d['delta'] >= 0 else ''}{d['delta']:.0f} pts)."
        )

    newly = [p for p, d in deltas.items() if d["trend"] == "newly_assessed"]
    if newly:
        lines.append(
            "Newly assessed this visit: " + ", ".join(PARAMETER_LABELS[p] for p in newly) + "."
        )
    missing = [p for p, d in deltas.items() if d["trend"] == "not_assessed_this_time"]
    if missing:
        lines.append(
            "Not covered by this visit's photos (previous score retained for reference): "
            + ", ".join(PARAMETER_LABELS[p] for p in missing) + "."
        )
    if not changed and not newly and not missing:
        lines.append("No parameter moved by more than a marginal amount since the last inspection.")

    return deltas, " ".join(lines), overall_trend
