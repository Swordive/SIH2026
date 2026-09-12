if (!getToken()) {
  window.location.href = "login.html";
}

const ROLE_LABELS = {
  admin: "Administrator",
  department_official: "Department Official",
  pmu_inspector: "PMU Inspector",
  project_incharge: "Project Incharge",
};

const PARAMETERS = ["cleanliness", "hygiene", "infrastructure", "safety", "maintenance", "aesthetics"];
const PARAMETER_LABELS = {
  cleanliness: "Cleanliness",
  hygiene: "Hygiene & Sanitation",
  infrastructure: "Infrastructure Condition",
  safety: "Safety",
  maintenance: "Maintenance & Upkeep",
  aesthetics: "Aesthetics & Presentation",
};

const GRADE_CLASS = {
  "Excellent": "grade-excellent",
  "Good": "grade-good",
  "Satisfactory": "grade-satisfactory",
  "Needs Improvement": "grade-needs-improvement",
  "Critical": "grade-critical",
};
const GRADE_OPTIONS = ["Excellent", "Good", "Satisfactory", "Needs Improvement", "Critical"];

const TREND_GLYPH = { improved: "▲ Improved", declined: "▼ Declined", stable: "● Stable" };

const params = new URLSearchParams(window.location.search);
const inspectionId = params.get("inspection");

let currentUserName = null;
let currentAnalysis = null;
let currentInspection = null;
let projectMap = {};
let userMap = {};
let editing = false;

function scoreColor(score) {
  if (score >= 90) return "var(--success)";
  if (score >= 75) return "var(--success)";
  if (score >= 60) return "var(--gold)";
  if (score >= 40) return "var(--red-accent)";
  return "var(--red-accent)";
}

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    currentUserName = me.full_name;
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
    hideLiveMonitoringNavIfInspector(me.role);
    return me;
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
    return null;
  }
}

async function buildLookups() {
  const [projects, users] = await Promise.all([
    apiFetch("/api/projects").catch(() => []),
    apiFetch("/api/users").catch(() => []),
  ]);
  projectMap = Object.fromEntries(projects.map((p) => [p.id, p.name]));
  userMap = Object.fromEntries(users.map((u) => [u.id, u.full_name]));
}

function showDenied(message) {
  document.getElementById("denied-state").style.display = "block";
  document.getElementById("analysis-content").style.display = "none";
  document.getElementById("denied-message").textContent = message;
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function renderHeader() {
  document.getElementById("analysis-project-name").textContent =
    projectMap[currentInspection.project_id] || currentInspection.project_id;
  document.getElementById("analysis-inspector-name").textContent =
    userMap[currentInspection.inspector_id] || currentInspection.inspector_id || "—";
  document.getElementById("analysis-completed-at").textContent = formatDate(currentInspection.completed_at);

  const sourceLabel = {
    vision_api: "Hosted vision-model analysis",
    heuristic: "Offline visual analysis",
    hybrid: "Mixed (vision-model + offline) analysis",
    text_only: "Written notes only (no photos submitted)",
  }[currentAnalysis.analysis_source] || currentAnalysis.analysis_source;
  document.getElementById("analysis-source").textContent = sourceLabel;

  document.getElementById("overall-score-value").textContent = Math.round(currentAnalysis.overall_score);
  const gradeBadge = document.getElementById("overall-grade-badge");
  gradeBadge.textContent = currentAnalysis.grade;
  gradeBadge.className = "score-gauge-grade " + (GRADE_CLASS[currentAnalysis.grade] || "");
  document.getElementById("score-gauge").style.setProperty("--gauge-pct", `${currentAnalysis.overall_score}%`);
  document.getElementById("score-gauge").style.setProperty("--gauge-color", scoreColor(currentAnalysis.overall_score));
}

function renderParamGrid() {
  const grid = document.getElementById("param-grid");
  grid.innerHTML = PARAMETERS.map((param) => {
    const score = currentAnalysis.parameter_scores[param];
    const count = currentAnalysis.ai_parameter_evidence_counts[param] || 0;
    const basis = count > 0 ? `${count} photo${count !== 1 ? "s" : ""}` : "not photographed";
    if (score == null) {
      return `
      <div class="param-card">
        <div class="param-card-head">
          <span>${PARAMETER_LABELS[param]}</span>
          <span class="param-score muted">N/A</span>
        </div>
        <div class="param-bar-track"><div class="param-bar-fill" style="width:0%; background:var(--border-strong);"></div></div>
        <p class="param-basis">Not assessed this visit</p>
      </div>`;
    }
    if (editing) {
      return `
      <div class="param-card">
        <div class="param-card-head">
          <span>${PARAMETER_LABELS[param]}</span>
          <input type="number" min="0" max="100" step="1" class="param-edit-input" data-param="${param}" value="${score}" />
        </div>
        <p class="param-basis">Based on ${basis}</p>
      </div>`;
    }
    return `
    <div class="param-card">
      <div class="param-card-head">
        <span>${PARAMETER_LABELS[param]}</span>
        <span class="param-score" style="color:${scoreColor(score)};">${Math.round(score)}</span>
      </div>
      <div class="param-bar-track"><div class="param-bar-fill" style="width:${score}%; background:${scoreColor(score)};"></div></div>
      <p class="param-basis">Based on ${basis}</p>
    </div>`;
  }).join("");
}

function renderComparison() {
  const card = document.getElementById("comparison-card");
  const body = document.getElementById("comparison-body");
  if (!currentAnalysis.previous_analysis_id) {
    body.innerHTML = `<p style="margin:0; color:var(--muted);">
      This is the first analyzed inspection for this project — there is nothing to compare against yet.
      Future inspections here will show whether conditions improved, declined, or stayed the same.
    </p>`;
    return;
  }
  const trendLabel = TREND_GLYPH[currentAnalysis.overall_trend] || currentAnalysis.overall_trend;
  const trendClass = `trend-${currentAnalysis.overall_trend}`;
  const rows = PARAMETERS
    .filter((p) => currentAnalysis.comparison_deltas && currentAnalysis.comparison_deltas[p])
    .map((p) => {
      const d = currentAnalysis.comparison_deltas[p];
      let right;
      if (d.trend === "newly_assessed") {
        right = `<span class="trend-badge trend-newly_assessed">New this visit</span>`;
      } else if (d.trend === "not_assessed_this_time") {
        right = `<span class="trend-badge trend-not_assessed_this_time">Not covered this visit</span>`;
      } else {
        const glyph = { improved: "▲", declined: "▼", stable: "●" }[d.trend];
        const sign = d.delta >= 0 ? "+" : "";
        right = `<span class="trend-badge trend-${d.trend}">${glyph} ${Math.round(d.previous)} → ${Math.round(d.current)} (${sign}${d.delta})</span>`;
      }
      return `<div class="comparison-row"><span>${PARAMETER_LABELS[p]}</span>${right}</div>`;
    })
    .join("");

  body.innerHTML = `
    <p class="comparison-overall ${trendClass}">Overall trend: ${trendLabel}</p>
    <div class="comparison-rows">${rows}</div>
    <p style="margin:14px 0 0; line-height:1.6;">${currentAnalysis.comparison_summary}</p>
  `;
}

function renderSummary() {
  document.getElementById("summary-view").textContent = currentAnalysis.summary;
  document.getElementById("summary-edit-text").value = currentAnalysis.summary;
  const note = document.getElementById("edited-by-note");
  if (currentAnalysis.is_edited && currentAnalysis.last_edited_at) {
    note.style.display = "block";
    note.textContent = `Last edited ${formatDate(currentAnalysis.last_edited_at)}. Original AI output is retained for reference.`;
  } else {
    note.style.display = "none";
  }
}

function renderPhotoBreakdown() {
  const grid = document.getElementById("photo-breakdown");
  const note = document.getElementById("no-photos-note");
  const photos = currentAnalysis.theme_breakdown || [];
  if (photos.length === 0) {
    grid.innerHTML = "";
    note.style.display = "block";
    return;
  }
  note.style.display = "none";
  grid.innerHTML = photos
    .map((photo) => {
      const scoreChips = Object.entries(photo.scores || {})
        .map(([param, score]) => `<span class="score-chip" style="border-color:${scoreColor(score)}; color:${scoreColor(score)};">${PARAMETER_LABELS[param] || param} ${Math.round(score)}</span>`)
        .join("");
      const flags = Object.entries(photo.quality_flags || {})
        .filter(([, v]) => v)
        .map(([k]) => `<span class="quality-flag-chip">${k.replace(/_/g, " ")}</span>`)
        .join("");
      const findings = (photo.findings || []).map((f) => `<li>${f}</li>`).join("");
      return `
      <div class="photo-card">
        <div class="photo-card-head">
          <span class="badge status-active">${photo.theme_label}</span>
          <span style="font-size:0.76rem; color:var(--muted);">${photo.source === "vision_api" ? "Vision-model analyzed" : "Offline analysis"}</span>
        </div>
        <div class="photo-card-scores">${scoreChips}</div>
        ${flags ? `<div class="photo-card-flags">${flags}</div>` : ""}
        <ul class="photo-card-findings">${findings}</ul>
      </div>`;
    })
    .join("");
}

function renderHistory() {
  const list = document.getElementById("history-list");
  const history = currentAnalysis.edit_history || [];
  if (history.length === 0) {
    list.innerHTML = `<p style="margin:0; color:var(--muted); font-size:0.88rem;">No manual edits have been made yet.</p>`;
    return;
  }
  list.innerHTML = history
    .slice()
    .reverse()
    .map((entry) => {
      const changeSummary = Object.keys(entry.changes || {}).join(", ");
      return `<div class="history-entry">
        <strong>${entry.editor_name}</strong> edited ${changeSummary || "the report"}
        <span style="color:var(--muted);"> — ${formatDate(entry.edited_at)}</span>
      </div>`;
    })
    .join("");
}

function renderAll() {
  renderHeader();
  renderParamGrid();
  renderComparison();
  renderSummary();
  renderPhotoBreakdown();
  renderHistory();
}

document.getElementById("edit-toggle-btn").addEventListener("click", () => {
  editing = true;
  document.getElementById("summary-view").style.display = "none";
  document.getElementById("summary-edit-form").style.display = "block";
  document.getElementById("edit-toggle-btn").style.display = "none";
  renderParamGrid();
});

function exitEditMode() {
  editing = false;
  document.getElementById("summary-view").style.display = "block";
  document.getElementById("summary-edit-form").style.display = "none";
  document.getElementById("edit-toggle-btn").style.display = "inline-block";
  document.getElementById("edit-error").style.display = "none";
  renderParamGrid();
}

document.getElementById("edit-cancel-btn").addEventListener("click", exitEditMode);

document.getElementById("summary-edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("edit-error");
  errorBox.style.display = "none";
  const saveBtn = document.getElementById("edit-save-btn");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";

  const parameter_scores = {};
  document.querySelectorAll(".param-edit-input").forEach((input) => {
    parameter_scores[input.dataset.param] = Number(input.value);
  });

  try {
    currentAnalysis = await apiFetch(`/api/inspections/${inspectionId}/analysis`, {
      method: "PATCH",
      body: {
        summary: document.getElementById("summary-edit-text").value.trim(),
        parameter_scores,
      },
    });
    exitEditMode();
    renderAll();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save changes";
  }
});

document.getElementById("history-toggle-btn").addEventListener("click", () => {
  const list = document.getElementById("history-list");
  const btn = document.getElementById("history-toggle-btn");
  const showing = list.style.display === "block";
  list.style.display = showing ? "none" : "block";
  btn.textContent = showing ? "Show edit history" : "Hide edit history";
});

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

async function init() {
  await loadUser();

  if (!inspectionId) {
    showDenied("No inspection was specified.");
    return;
  }

  try {
    const [inspection, analysis] = await Promise.all([
      apiFetch(`/api/inspections/${inspectionId}`),
      apiFetch(`/api/inspections/${inspectionId}/analysis`),
    ]);
    currentInspection = inspection;
    currentAnalysis = analysis;
    await buildLookups();
    document.getElementById("analysis-content").style.display = "block";
    document.getElementById("denied-state").style.display = "none";
    renderAll();
  } catch (err) {
    if (err.message && err.message.toLowerCase().includes("not found")) {
      showDenied("No analysis report exists yet for this inspection — it hasn't been submitted.");
    } else {
      showDenied(
        "This report isn't visible to your role. The AI analysis report is available to everyone except the inspector who submitted it."
      );
    }
  }
}

init();
