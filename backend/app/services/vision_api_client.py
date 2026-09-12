"""
Optional multi-provider hosted-vision-API client for inspection-photo
analysis.

This is the "smart" path for app/services/ai_inspection_analysis.py:
given a photo, ask a real vision-language model to (a) classify what
the photo is actually a picture of, from GOV-INSPECT's fixed theme
taxonomy, and (b) score it on whichever quality parameters that theme
implies. It is entirely optional -- see app/config.py -- and the
calling code always has a fully-offline OpenCV-heuristic fallback, so
a missing key, an expired key, a provider outage, or (as in this
sandboxed build) no network access at all never breaks report
submission; it just means photos get scored by the heuristic path
instead of a hosted model.

Deliberately supports three providers rather than hardcoding one:
different deployments will have different existing API relationships
(a state IT department already paying for Google Cloud, an NGO with
an OpenAI credit grant, etc.), and trying more than one in sequence
also means a single provider's outage/rate-limit doesn't take the
whole feature down. Providers are tried in settings.VISION_PROVIDER_ORDER
and the first one that returns a usable, well-formed result wins.

Every provider is asked to return ONLY a JSON object shaped like:
{
  "theme": "<one of the taxonomy keys, verbatim>",
  "confidence": <0.0-1.0>,
  "parameters": {"<parameter>": <0-100 number>, ...},
  "findings": ["<short observation>", ...]
}
Anything else -- a parse failure, an HTTP error, a timeout, a missing
key -- is treated as "this provider had nothing usable" and silently
falls through to the next one / the offline heuristic.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VisionResult:
    theme: str
    confidence: float
    parameters: dict[str, float]
    findings: list[str]
    provider: str


def _build_prompt(theme_catalogue: dict[str, dict], caption: str | None) -> str:
    theme_list = "\n".join(
        f'- "{key}": {info["label"]} (relevant parameters: {", ".join(info["weights"])})'
        for key, info in theme_catalogue.items()
    )
    caption_line = f'The inspector captioned this photo: "{caption.strip()}"\n' if caption else ""
    return (
        "You are assisting a government infrastructure-monitoring system. "
        "Look at the attached inspection photo and classify it against this "
        "fixed taxonomy of site themes (pick exactly one key):\n"
        f"{theme_list}\n\n"
        f"{caption_line}"
        "Then score the photo from 0-100 on ONLY the parameters listed as "
        "relevant for the theme you picked (higher = better condition). "
        "Also list 2-4 short, specific, factual visual observations that "
        "justify the scores (e.g. 'visible water stains on ceiling tiles', "
        "'floor appears freshly mopped', 'exposed wiring near switchboard'). "
        "Do not invent details you cannot actually see.\n\n"
        "Respond with ONLY a single JSON object, no prose, no markdown "
        "fences, in exactly this shape:\n"
        '{"theme": "<taxonomy key>", "confidence": <0.0-1.0>, '
        '"parameters": {"<parameter>": <0-100>, ...}, "findings": ["...", "..."]}'
    )


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction: models occasionally wrap the
    object in ```json fences or add a stray sentence despite
    instructions not to. Grabs the first {...} span and parses that."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_result(
    raw: dict, theme_catalogue: dict[str, dict], provider: str
) -> VisionResult | None:
    theme = raw.get("theme")
    if theme not in theme_catalogue:
        return None
    params_raw = raw.get("parameters")
    if not isinstance(params_raw, dict):
        return None
    allowed = set(theme_catalogue[theme]["weights"])
    parameters = {}
    for key, value in params_raw.items():
        if key not in allowed:
            continue
        try:
            parameters[key] = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            continue
    if not parameters:
        return None
    findings = raw.get("findings")
    if not isinstance(findings, list):
        findings = []
    findings = [str(f).strip() for f in findings if str(f).strip()][:5]
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.6))))
    except (TypeError, ValueError):
        confidence = 0.6
    return VisionResult(
        theme=theme, confidence=confidence, parameters=parameters,
        findings=findings, provider=provider,
    )


def _call_anthropic(image_b64: str, media_type: str, prompt: str) -> dict | None:
    if not settings.ANTHROPIC_API_KEY:
        return None
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 700,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        },
        timeout=settings.VISION_API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    return _extract_json(text)


def _call_openai(image_b64: str, media_type: str, prompt: str) -> dict | None:
    if not settings.OPENAI_API_KEY:
        return None
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                    ],
                }
            ],
            "max_tokens": 700,
        },
        timeout=settings.VISION_API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return _extract_json(text)


def _call_google(image_b64: str, media_type: str, prompt: str) -> dict | None:
    if not settings.GOOGLE_API_KEY:
        return None
    resp = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={settings.GOOGLE_API_KEY}",
        json={
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": media_type, "data": image_b64}},
                    ]
                }
            ]
        },
        timeout=settings.VISION_API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _extract_json(text)


_PROVIDER_FUNCS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "google": _call_google,
}


def classify_and_score(
    image_bytes: bytes,
    media_type: str,
    caption: str | None,
    theme_catalogue: dict[str, dict],
) -> VisionResult | None:
    """Tries each configured provider in settings.VISION_PROVIDER_ORDER
    in turn. Returns None (never raises) if none are configured, none
    are reachable, or none return a usable result -- the caller falls
    back to the offline heuristic in that case."""
    if not any([settings.ANTHROPIC_API_KEY, settings.OPENAI_API_KEY, settings.GOOGLE_API_KEY]):
        return None

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = _build_prompt(theme_catalogue, caption)

    for provider in settings.VISION_PROVIDER_ORDER:
        func = _PROVIDER_FUNCS.get(provider)
        if func is None:
            continue
        try:
            raw = func(image_b64, media_type, prompt)
        except Exception as exc:  # network down, bad key, rate limit, etc.
            logger.info("Vision provider %s unavailable: %s", provider, exc)
            continue
        if not raw:
            continue
        result = _validate_result(raw, theme_catalogue, provider)
        if result:
            return result
    return None
