if (!getToken()) {
  window.location.href = "login.html";
}

const ROLE_LABELS = {
  admin: "Administrator",
  department_official: "Department Official",
  pmu_inspector: "PMU Inspector",
  project_incharge: "Project Incharge",
};

const STATUS_LABELS = {
  pending: "Pending",
  in_progress: "In progress",
  completed: "Completed",
  missed: "Missed",
};

const TYPE_LABELS = {
  surprise: "Surprise visit",
  scheduled: "Scheduled",
  vc_random: "Random VC check-in",
};

let currentInspections = [];
let projectMap = {};
let projectOptions = []; // [{id, name}]
let userMap = {};
let inspectorOptions = []; // [{id, full_name}]
let canManage = false;
let assigningInspectionId = null;
let feedInspectionId = null;
let currentUserId = null;
let currentUserName = null;
let currentUserRole = null;
let myProjectIds = new Set(); // for project_incharge: which projects are theirs
let checkinInspectionId = null;
let checkinLatitude = null;
let checkinLongitude = null;
let reportInspectionId = null;
let reportLatitude = null;
let reportLongitude = null;
let reportPendingFiles = []; // [{file, caption}] queued for upload on submit
let analysisSummary = {}; // {inspection_id: {overall_score, grade, overall_trend, is_edited}} — non-inspector only

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    currentUserId = me.id;
    currentUserName = me.full_name;
    currentUserRole = me.role;
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
    hideLiveMonitoringNavIfInspector(me.role);
    canManage =
      me.role === "admin" ||
      me.role === "department_official" ||
      me.role === "project_incharge";
    document.getElementById("run-assignment-btn").style.display = canManage
      ? "inline-block"
      : "none";
    document.getElementById("toggle-manual-form").style.display = canManage
      ? "inline-block"
      : "none";

    // Live Monitoring is now open to every role -- feeds live on
    // individual inspections and /api/inspections already scopes what
    // each role can see, so there's nothing left to gate here.
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
  }
}

// Inspections only carry IDs, so build lookup maps to show readable
// project/inspector names instead of raw UUIDs.
async function buildLookups() {
  const [projects, users] = await Promise.all([
    apiFetch("/api/projects").catch(() => []),
    apiFetch("/api/users").catch(() => []), // may 403 for non-admins; that's fine
  ]);

  projectMap = Object.fromEntries(projects.map((p) => [p.id, p.name]));
  projectOptions = projects.map((p) => ({ id: p.id, name: p.name }));
  userMap = Object.fromEntries(users.map((u) => [u.id, u.full_name]));
  inspectorOptions = users.filter((u) => u.role === "pmu_inspector" && u.is_active);
  myProjectIds = new Set(
    projects.filter((p) => p.incharge_id === currentUserId).map((p) => p.id)
  );
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function inspectorDisplayName(inspectorId) {
  if (userMap[inspectorId]) return userMap[inspectorId];
  // PMU inspectors can't fetch /api/users (admin/dept-official only),
  // so userMap is empty for them -- fall back to their own identity
  // for their own rows, which is the only case they'll ever see now.
  if (inspectorId === currentUserId && currentUserName) return currentUserName;
  return inspectorId;
}

// Check-in (GPS + AI face-check) is an inspector-only action on
// their own pending/in-progress inspections -- it's the thing being
// verified, so it can't also be performed by the people reviewing
// the verification.
function canCheckIn(inspection) {
  if (inspection.status !== "pending" && inspection.status !== "in_progress") {
    return false;
  }
  return (
    currentUserRole === "pmu_inspector" &&
    inspection.inspector_id === currentUserId
  );
}

// A video call to check on an inspector isn't limited to the
// "Random VC check-in" type -- admins/department officials (and a
// project's own incharge) can call in on an inspector during ANY
// ongoing inspection (surprise visit, scheduled, or vc_random) to
// see how it's going. The backend (_can_join in app/api/routes/vc.py)
// never restricted this by inspection_type either -- it only ever
// checked role/ownership -- so this mirrors what the server already
// allows instead of hiding a capability that was really there.
function canJoinVC(inspection) {
  if (inspection.status !== "pending" && inspection.status !== "in_progress") {
    return false;
  }
  if (currentUserRole === "admin" || currentUserRole === "department_official") {
    return true;
  }
  if (currentUserRole === "pmu_inspector") {
    return inspection.inspector_id === currentUserId;
  }
  if (currentUserRole === "project_incharge") {
    return myProjectIds.has(inspection.project_id);
  }
  return false;
}

// Submitting the inspection report (text + photo evidence) is an
// inspector-only action on their own not-yet-completed inspection --
// once COMPLETED, the report (and the AI analysis built from it) is
// locked in; resubmission isn't supported from this screen.
function canSubmitReport(inspection) {
  if (inspection.status === "completed" || inspection.status === "missed") return false;
  if (currentUserRole === "pmu_inspector") {
    return inspection.inspector_id === currentUserId;
  }
  // Admins can file a report on anyone's inspection too -- lets you
  // exercise the AI analysis pipeline (and see the resulting "View
  // analysis" page) without switching accounts. The backend already
  // allows this (submit-report and evidence/upload only enforce
  // ownership for pmu_inspector, not admin); this just surfaces the
  // button here.
  return currentUserRole === "admin";
}

// The AI analysis report is viewable/editable by every role except
// pmu_inspector (see InspectionAnalysisReport's docstring on the
// backend) -- and only exists once a report has actually been
// submitted.
function canViewAnalysis(inspection) {
  return canManage && inspection.status === "completed";
}

function actionsCell(inspection) {
  const buttons = [];

  if (canManage) {
    const assignLabel = inspection.inspector_id ? "Reassign" : "Assign";
    const feedLabel = inspection.cctv_feed_url ? "Edit feed" : "Set feed";
    buttons.push(
      `<button class="row-action" data-action="assign" data-id="${inspection.id}">${assignLabel}</button>`
    );
    buttons.push(
      `<button class="row-action" data-action="feed" data-id="${inspection.id}">${feedLabel}</button>`
    );
  }

  if (canCheckIn(inspection)) {
    const label = inspection.attendance_marked_at ? "Check in again" : "Check in";
    buttons.push(
      `<button class="row-action" data-action="checkin" data-id="${inspection.id}">${label}</button>`
    );
  }

  if (canSubmitReport(inspection)) {
    const label = inspection.report_text ? "Update report" : "Submit report";
    buttons.push(
      `<button class="row-action" data-action="report" data-id="${inspection.id}">${label}</button>`
    );
  }

  if (canViewAnalysis(inspection)) {
    buttons.push(
      `<a class="row-action" href="analysis.html?inspection=${inspection.id}">View analysis</a>`
    );
  }

  if (canJoinVC(inspection)) {
    buttons.push(
      `<a class="row-action" href="video-call.html?inspection=${inspection.id}">Join call</a>`
    );
  }

  if (canManage) {
    buttons.push(
      `<button class="row-action danger" data-action="delete" data-id="${inspection.id}">Delete</button>`
    );
  }

  return buttons.length ? buttons.join("") : "—";
}

// "Report" column: whether the inspector has filed a written report
// yet, and — for every role except pmu_inspector, who never sees the
// AI's review of their own work — the resulting score/grade once the
// AI analysis has run.
function reportCell(inspection) {
  if (!inspection.report_text) {
    return `<span class="badge status-inactive">Not submitted</span>`;
  }
  if (currentUserRole === "pmu_inspector") {
    return `<span class="badge status-active">Submitted</span>`;
  }
  const summary = analysisSummary[inspection.id];
  if (!summary) {
    return `<span class="badge status-active">Submitted</span>`;
  }
  const gradeClass = GRADE_BADGE_CLASS[summary.grade] || "status-active";
  const trendGlyph = { improved: "▲", declined: "▼", stable: "●", new_baseline: "" }[summary.overall_trend] || "";
  const editedTag = summary.is_edited ? " · edited" : "";
  return `<span class="badge ${gradeClass}">${Math.round(summary.overall_score)}/100 · ${summary.grade}${trendGlyph ? " " + trendGlyph : ""}${editedTag}</span>`;
}

const GRADE_BADGE_CLASS = {
  "Excellent": "status-active",
  "Good": "status-active",
  "Satisfactory": "severity-medium",
  "Needs Improvement": "severity-high",
  "Critical": "severity-critical",
};

function aiCheckCell(inspection) {
  if (!inspection.attendance_face_checked_at) {
    return `<span class="badge status-inactive">Not checked</span>`;
  }

  const badges = [];

  badges.push(
    inspection.attendance_face_verified
      ? `<span class="badge status-active">Face OK</span>`
      : `<span class="badge severity-high">Face flagged (${inspection.attendance_face_count ?? "?"})</span>`
  );

  if (inspection.attendance_distance_meters == null) {
    badges.push(`<span class="badge status-inactive">No site GPS on file</span>`);
  } else {
    const meters = Math.round(inspection.attendance_distance_meters);
    badges.push(
      meters <= 250
        ? `<span class="badge status-active">On-site (${meters}m)</span>`
        : `<span class="badge severity-high">Off-site (${meters}m)</span>`
    );
  }

  if (inspection.attendance_duplicate_detected) {
    badges.push(`<span class="badge severity-high">Reused photo</span>`);
  }

  return badges.join("<br />");
}

async function loadInspections() {
  const tbody = document.getElementById("inspections-body");
  const emptyState = document.getElementById("empty-state");

  try {
    const inspections = await apiFetch("/api/inspections");
    currentInspections = inspections;
    await buildLookups();
    populateManualProjectDropdown();

    // Only fetched for roles that are actually allowed to see it --
    // pmu_inspector would get a 403 (they never see the AI's review
    // of their own submitted work), so don't even ask.
    if (canManage) {
      analysisSummary = await apiFetch("/api/inspections/analysis/summary").catch(() => ({}));
    } else {
      analysisSummary = {};
    }

    if (inspections.length === 0) {
      emptyState.style.display = "block";
      tbody.innerHTML = "";
      return;
    }
    emptyState.style.display = "none";

    tbody.innerHTML = inspections
      .map((i) => `
      <tr>
        <td>${projectMap[i.project_id] || i.project_id}</td>
        <td>${i.inspector_id ? inspectorDisplayName(i.inspector_id) : "Unassigned"}</td>
        <td>${TYPE_LABELS[i.inspection_type] || i.inspection_type}</td>
        <td>${STATUS_LABELS[i.status] || i.status}</td>
        <td>${i.ai_assigned ? "AI / automation" : "Manual"}</td>
        <td>${formatDate(i.scheduled_at)}</td>
        <td>${i.cctv_feed_url ? "Connected" : "Not configured"}</td>
        <td>${aiCheckCell(i)}</td>
        <td>${reportCell(i)}</td>
        <td>${actionsCell(i)}</td>
      </tr>`)
      .join("");
  } catch (err) {
    tbody.innerHTML = "";
  }
}

document.getElementById("run-assignment-btn").addEventListener("click", async () => {
  const btn = document.getElementById("run-assignment-btn");
  const statusEl = document.getElementById("run-status");

  btn.disabled = true;
  btn.textContent = "Running…";
  statusEl.style.display = "none";

  try {
    const created = await apiFetch("/api/inspections/auto-assign?max_assignments=5", {
      method: "POST",
    });
    statusEl.textContent = created.length
      ? `Created ${created.length} new inspection${created.length === 1 ? "" : "s"}. Assign an inspector and date/time for each below.`
      : "No projects exist yet to assign an inspection to.";
    statusEl.style.color = "var(--success)";
    statusEl.style.display = "block";
    await loadInspections();
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.style.color = "var(--red-accent)";
    statusEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Run random assignment";
  }
});

// ---- Manual add-inspection form ----

const manualForm = document.getElementById("manual-add-form");
const manualProjectSelect = document.getElementById("manual-project");
const manualTypeSelect = document.getElementById("manual-type");
const manualCctvInput = document.getElementById("manual-cctv");
const manualSubmitBtn = document.getElementById("manual-add-submit");
const manualErrorBox = document.getElementById("manual-add-error");

function populateManualProjectDropdown() {
  manualProjectSelect.innerHTML =
    '<option value="">Select a project…</option>' +
    projectOptions.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
}

document.getElementById("toggle-manual-form").addEventListener("click", () => {
  manualForm.classList.toggle("open");
});
document.getElementById("manual-add-cancel").addEventListener("click", () => {
  manualForm.classList.remove("open");
  manualForm.reset();
});

manualForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  manualErrorBox.style.display = "none";
  const projectId = manualProjectSelect.value;
  if (!projectId) return;

  const inspectionType = manualTypeSelect.value;
  const cctvFeedUrl = manualCctvInput.value.trim();

  manualSubmitBtn.disabled = true;
  manualSubmitBtn.textContent = "Adding…";

  try {
    const params = new URLSearchParams({
      project_id: projectId,
      inspection_type: inspectionType,
    });
    if (cctvFeedUrl) params.set("cctv_feed_url", cctvFeedUrl);

    await apiFetch(`/api/inspections/manual?${params.toString()}`, { method: "POST" });
    manualForm.classList.remove("open");
    manualForm.reset();
    await loadInspections();
  } catch (err) {
    manualErrorBox.textContent = err.message;
    manualErrorBox.style.display = "block";
  } finally {
    manualSubmitBtn.disabled = false;
    manualSubmitBtn.textContent = "Add inspection";
  }
});

// ---- Assign form ----

const assignForm = document.getElementById("assign-form");
const assignInspectorSelect = document.getElementById("assign-inspector");
const assignDatetimeInput = document.getElementById("assign-datetime");
const assignSubmitBtn = document.getElementById("assign-submit");
const assignErrorBox = document.getElementById("assign-error");

function openAssignForm(inspection) {
  assigningInspectionId = inspection.id;
  document.getElementById("assign-project-name").textContent =
    projectMap[inspection.project_id] || inspection.project_id;

  assignInspectorSelect.innerHTML =
    '<option value="">Select an inspector…</option>' +
    inspectorOptions
      .map((u) => `<option value="${u.id}">${u.full_name}</option>`)
      .join("");
  if (inspection.inspector_id) assignInspectorSelect.value = inspection.inspector_id;

  assignDatetimeInput.value = inspection.scheduled_at
    ? inspection.scheduled_at.slice(0, 16) // trim to "YYYY-MM-DDTHH:mm" for the input
    : "";

  assignErrorBox.style.display = "none";
  assignForm.classList.add("open");
  assignForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeAssignForm() {
  assigningInspectionId = null;
  assignForm.classList.remove("open");
  assignForm.reset();
}

document.getElementById("assign-cancel").addEventListener("click", closeAssignForm);

// ---- Feed form ----

const feedForm = document.getElementById("feed-form");
const feedUrlInput = document.getElementById("feed-url");
const feedSubmitBtn = document.getElementById("feed-submit");
const feedErrorBox = document.getElementById("feed-error");

function openFeedForm(inspection) {
  feedInspectionId = inspection.id;
  document.getElementById("feed-project-name").textContent =
    projectMap[inspection.project_id] || inspection.project_id;
  feedUrlInput.value = inspection.cctv_feed_url || "";
  feedErrorBox.style.display = "none";
  feedForm.classList.add("open");
  feedForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeFeedForm() {
  feedInspectionId = null;
  feedForm.classList.remove("open");
  feedForm.reset();
}

document.getElementById("feed-cancel").addEventListener("click", closeFeedForm);

feedForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  feedErrorBox.style.display = "none";
  feedSubmitBtn.disabled = true;
  feedSubmitBtn.textContent = "Saving…";

  try {
    await apiFetch(`/api/inspections/${feedInspectionId}`, {
      method: "PATCH",
      body: { cctv_feed_url: feedUrlInput.value.trim() || null },
    });
    closeFeedForm();
    await loadInspections();
  } catch (err) {
    feedErrorBox.textContent = err.message;
    feedErrorBox.style.display = "block";
  } finally {
    feedSubmitBtn.disabled = false;
    feedSubmitBtn.textContent = "Save feed";
  }
});

// ---- Check-in form (attendance + optional AI face-check) ----

const checkinForm = document.getElementById("checkin-form");
const checkinSubmitBtn = document.getElementById("checkin-submit");
const checkinErrorBox = document.getElementById("checkin-error");
const checkinResultBox = document.getElementById("checkin-result");
const checkinPhotoInput = document.getElementById("checkin-photo");
const checkinGpsStatus = document.getElementById("checkin-gps-status");

function updateCheckinSubmitState() {
  const ready = checkinLatitude != null && checkinLongitude != null;
  checkinSubmitBtn.disabled = !ready;
  checkinSubmitBtn.textContent = ready ? "Check in" : "Capture location first";
}

function openCheckinForm(inspection) {
  checkinInspectionId = inspection.id;
  checkinLatitude = null;
  checkinLongitude = null;
  document.getElementById("checkin-project-name").textContent =
    projectMap[inspection.project_id] || inspection.project_id;
  checkinGpsStatus.textContent = "Not captured yet";
  checkinErrorBox.style.display = "none";
  checkinResultBox.style.display = "none";
  updateCheckinSubmitState();
  checkinForm.classList.add("open");
  checkinForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeCheckinForm() {
  checkinInspectionId = null;
  checkinLatitude = null;
  checkinLongitude = null;
  checkinForm.classList.remove("open");
  checkinForm.reset();
  updateCheckinSubmitState();
}

document.getElementById("checkin-cancel").addEventListener("click", closeCheckinForm);

document.getElementById("checkin-capture-gps").addEventListener("click", () => {
  if (!navigator.geolocation) {
    checkinGpsStatus.textContent = "Geolocation not supported by this browser — check-in requires it";
    return;
  }
  checkinGpsStatus.textContent = "Capturing…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      checkinLatitude = pos.coords.latitude;
      checkinLongitude = pos.coords.longitude;
      checkinGpsStatus.textContent = `${checkinLatitude.toFixed(5)}, ${checkinLongitude.toFixed(5)}`;
      updateCheckinSubmitState();
    },
    (err) => {
      checkinGpsStatus.textContent = `Could not get location (${err.message}) — required to check in`;
      checkinLatitude = null;
      checkinLongitude = null;
      updateCheckinSubmitState();
    },
    { enableHighAccuracy: true }
  );
});

checkinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  checkinErrorBox.style.display = "none";
  checkinResultBox.style.display = "none";

  const photoFile = checkinPhotoInput.files[0];
  if (checkinLatitude == null || checkinLongitude == null) {
    checkinErrorBox.textContent = "Capture your GPS location before checking in.";
    checkinErrorBox.style.display = "block";
    return;
  }
  if (!photoFile) {
    checkinErrorBox.textContent = "An attendance selfie is required to check in.";
    checkinErrorBox.style.display = "block";
    return;
  }

  checkinSubmitBtn.disabled = true;
  checkinSubmitBtn.textContent = "Checking in…";

  try {
    const result = await apiUploadForm(
      `/api/inspections/${checkinInspectionId}/checkin`,
      { latitude: checkinLatitude, longitude: checkinLongitude, photo: photoFile }
    );

    const resultLines = [
      result.face_verified
        ? "Face check: 1 face detected — verified."
        : `Face check: ${result.face_count} faces detected — flagged for review.`,
    ];
    if (result.within_geofence == null) {
      resultLines.push("Location check: project has no registered site coordinates yet — skipped.");
    } else if (result.within_geofence) {
      resultLines.push(`Location check: ${Math.round(result.distance_meters)}m from the registered site — on-site.`);
    } else {
      resultLines.push(`Location check: ${Math.round(result.distance_meters)}m from the registered site — flagged for review.`);
    }
    if (result.duplicate_photo_detected) {
      resultLines.push("Duplicate check: this selfie matches a previous check-in photo — flagged for review.");
    }

    checkinResultBox.textContent = resultLines.join(" ");
    checkinResultBox.style.display = "block";
    await loadInspections();
  } catch (err) {
    checkinErrorBox.textContent = err.message;
    checkinErrorBox.style.display = "block";
  } finally {
    updateCheckinSubmitState();
  }
});

// ---- Report form (written findings + AI-analyzed photo evidence) ----

const reportForm = document.getElementById("report-form");
const reportSubmitBtn = document.getElementById("report-submit");
const reportErrorBox = document.getElementById("report-error");
const reportResultBox = document.getElementById("report-result");
const reportTextInput = document.getElementById("report-text");
const reportPhotosInput = document.getElementById("report-photos");
const reportPhotoList = document.getElementById("report-photo-list");
const reportGpsStatus = document.getElementById("report-gps-status");

function openReportForm(inspection) {
  reportInspectionId = inspection.id;
  reportLatitude = null;
  reportLongitude = null;
  reportPendingFiles = [];
  document.getElementById("report-project-name").textContent =
    projectMap[inspection.project_id] || inspection.project_id;
  reportTextInput.value = inspection.report_text || "";
  reportGpsStatus.textContent = "Not captured";
  reportErrorBox.style.display = "none";
  reportResultBox.style.display = "none";
  reportPhotosInput.value = "";
  renderReportPhotoList();
  reportForm.classList.add("open");
  reportForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeReportForm() {
  reportInspectionId = null;
  reportLatitude = null;
  reportLongitude = null;
  reportPendingFiles = [];
  reportForm.classList.remove("open");
  reportForm.reset();
  renderReportPhotoList();
}

document.getElementById("report-cancel").addEventListener("click", closeReportForm);

document.getElementById("report-capture-gps").addEventListener("click", () => {
  if (!navigator.geolocation) {
    reportGpsStatus.textContent = "Geolocation not supported by this browser";
    return;
  }
  reportGpsStatus.textContent = "Capturing…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      reportLatitude = pos.coords.latitude;
      reportLongitude = pos.coords.longitude;
      reportGpsStatus.textContent = `${reportLatitude.toFixed(5)}, ${reportLongitude.toFixed(5)}`;
    },
    (err) => {
      reportGpsStatus.textContent = `Could not get location (${err.message})`;
      reportLatitude = null;
      reportLongitude = null;
    },
    { enableHighAccuracy: true }
  );
});

// Queues newly picked photos (with an editable caption each) rather
// than uploading immediately on selection -- the inspector may want
// to caption several at once before anything hits the network, and a
// mis-added photo should be removable before it's ever analyzed.
reportPhotosInput.addEventListener("change", () => {
  for (const file of reportPhotosInput.files) {
    reportPendingFiles.push({ file, caption: "", status: "queued" });
  }
  reportPhotosInput.value = "";
  renderReportPhotoList();
});

function renderReportPhotoList() {
  if (reportPendingFiles.length === 0) {
    reportPhotoList.innerHTML = "";
    return;
  }
  reportPhotoList.innerHTML = reportPendingFiles
    .map((entry, idx) => {
      const url = URL.createObjectURL(entry.file);
      const statusBadge = {
        queued: `<span class="badge status-inactive">Queued</span>`,
        uploading: `<span class="badge severity-medium">Analyzing…</span>`,
        done: entry.result
          ? `<span class="badge status-active">${entry.result.theme_label} · ${formatScoreChips(entry.result.parameter_scores)}</span>`
          : `<span class="badge status-active">Analyzed</span>`,
        error: `<span class="badge severity-high">Failed — will retry on submit</span>`,
      }[entry.status];
      return `
      <div class="evidence-upload-row" data-idx="${idx}">
        <img src="${url}" alt="" class="evidence-thumb" />
        <div class="evidence-upload-meta">
          <input type="text" class="evidence-caption-input" data-idx="${idx}"
            placeholder="Caption (e.g. Boys' washroom, ground floor)" value="${entry.caption.replace(/"/g, "&quot;")}"
            ${entry.status === "uploading" || entry.status === "done" ? "disabled" : ""} />
          ${statusBadge}
          ${entry.result && entry.result.findings && entry.result.findings.length
            ? `<span class="evidence-finding">${entry.result.findings[0]}</span>`
            : ""}
        </div>
        ${entry.status === "queued" ? `<button type="button" class="row-action danger" data-remove-idx="${idx}">Remove</button>` : ""}
      </div>`;
    })
    .join("");
}

function formatScoreChips(scores) {
  if (!scores) return "";
  return Object.entries(scores)
    .map(([param, score]) => `${param} ${Math.round(score)}`)
    .join(", ");
}

reportPhotoList.addEventListener("input", (e) => {
  if (e.target.classList.contains("evidence-caption-input")) {
    const idx = Number(e.target.dataset.idx);
    if (reportPendingFiles[idx]) reportPendingFiles[idx].caption = e.target.value;
  }
});

reportPhotoList.addEventListener("click", (e) => {
  const removeBtn = e.target.closest("button[data-remove-idx]");
  if (!removeBtn) return;
  const idx = Number(removeBtn.dataset.removeIdx);
  reportPendingFiles.splice(idx, 1);
  renderReportPhotoList();
});

reportForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  reportErrorBox.style.display = "none";
  reportResultBox.style.display = "none";

  if (!reportTextInput.value.trim()) {
    reportErrorBox.textContent = "Written findings are required.";
    reportErrorBox.style.display = "block";
    return;
  }

  reportSubmitBtn.disabled = true;

  // Upload photos one at a time (not in parallel) so the progress
  // label and each row's "Analyzing…" badge stay meaningful, and so
  // one large photo doesn't compete for bandwidth with the rest.
  const toUpload = reportPendingFiles.filter((e) => e.status === "queued" || e.status === "error");
  for (let i = 0; i < toUpload.length; i++) {
    const entry = toUpload[i];
    entry.status = "uploading";
    renderReportPhotoList();
    reportSubmitBtn.textContent = `Analyzing photo ${i + 1} of ${toUpload.length}…`;
    try {
      const result = await apiUploadForm(
        `/api/inspections/${reportInspectionId}/evidence/upload`,
        { photo: entry.file, caption: entry.caption || "" }
      );
      entry.status = "done";
      entry.result = result;
    } catch (err) {
      entry.status = "error";
      reportErrorBox.textContent = `Could not analyze one of the photos: ${err.message}`;
      reportErrorBox.style.display = "block";
      renderReportPhotoList();
      reportSubmitBtn.disabled = false;
      reportSubmitBtn.textContent = "Submit report";
      return;
    }
    renderReportPhotoList();
  }

  reportSubmitBtn.textContent = "Finalizing report…";

  try {
    await apiFetch(`/api/inspections/${reportInspectionId}/submit-report`, {
      method: "POST",
      body: {
        report_text: reportTextInput.value.trim(),
        report_latitude: reportLatitude,
        report_longitude: reportLongitude,
      },
    });
    reportResultBox.textContent =
      "Report submitted. The AI analysis has been generated" +
      (currentUserRole === "pmu_inspector" ? " for reviewers to see." : " — open \u201cView analysis\u201d to review it.");
    reportResultBox.style.display = "block";
    reportPendingFiles = [];
    await loadInspections();
    setTimeout(closeReportForm, 1400);
  } catch (err) {
    reportErrorBox.textContent = err.message;
    reportErrorBox.style.display = "block";
  } finally {
    reportSubmitBtn.disabled = false;
    reportSubmitBtn.textContent = "Submit report";
  }
});

document.getElementById("inspections-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;

  const inspection = currentInspections.find((i) => i.id === btn.dataset.id);
  if (!inspection) return;

  if (btn.dataset.action === "assign") {
    openAssignForm(inspection);
    return;
  }

  if (btn.dataset.action === "feed") {
    openFeedForm(inspection);
    return;
  }

  if (btn.dataset.action === "checkin") {
    openCheckinForm(inspection);
    return;
  }

  if (btn.dataset.action === "report") {
    openReportForm(inspection);
    return;
  }

  if (btn.dataset.action === "delete") {
    const confirmed = confirm(
      `Delete this inspection for "${projectMap[inspection.project_id] || inspection.project_id}"? This cannot be undone.`
    );
    if (!confirmed) return;

    btn.disabled = true;
    btn.textContent = "Deleting…";
    try {
      await apiFetch(`/api/inspections/${inspection.id}`, { method: "DELETE" });
      if (assigningInspectionId === inspection.id) closeAssignForm();
      if (feedInspectionId === inspection.id) closeFeedForm();
      if (checkinInspectionId === inspection.id) closeCheckinForm();
      if (reportInspectionId === inspection.id) closeReportForm();
      await loadInspections();
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
      btn.textContent = "Delete";
    }
  }
});

assignForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  assignErrorBox.style.display = "none";
  assignSubmitBtn.disabled = true;
  assignSubmitBtn.textContent = "Saving…";

  const payload = {
    inspector_id: assignInspectorSelect.value,
    // datetime-local has no timezone; new Date(...).toISOString() takes
    // it as local time and converts to UTC for the API.
    scheduled_at: new Date(assignDatetimeInput.value).toISOString(),
  };

  try {
    await apiFetch(`/api/inspections/${assigningInspectionId}/assign`, {
      method: "PATCH",
      body: payload,
    });
    closeAssignForm();
    await loadInspections();
  } catch (err) {
    assignErrorBox.textContent = err.message;
    assignErrorBox.style.display = "block";
  } finally {
    assignSubmitBtn.disabled = false;
    assignSubmitBtn.textContent = "Save assignment";
  }
});

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

// loadUser() sets currentUserId/currentUserRole/canManage, all of
// which loadInspections() needs (via buildLookups()'s myProjectIds,
// and via canManage/canJoinVC in actionsCell) to render the action
// buttons correctly. Firing both at once raced them: whichever
// resolved first rendered the table using stale/default values, with
// nothing to trigger a re-render once the other caught up -- so
// "Join call", "Assign", "Delete" etc. could silently disappear for
// an entire page load depending on network timing. Sequencing them
// fixes that.
async function init() {
  await loadUser();
  await loadInspections();
}
init();
