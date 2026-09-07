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

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    currentUserId = me.id;
    currentUserName = me.full_name;
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
    canManage = me.role === "admin" || me.role === "department_official";
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

function actionsCell(inspection) {
  if (!canManage) return "—";
  const assignLabel = inspection.inspector_id ? "Reassign" : "Assign";
  const feedLabel = inspection.cctv_feed_url ? "Edit feed" : "Set feed";
  return `
    <button class="row-action" data-action="assign" data-id="${inspection.id}">${assignLabel}</button>
    <button class="row-action" data-action="feed" data-id="${inspection.id}">${feedLabel}</button>
    <button class="row-action danger" data-action="delete" data-id="${inspection.id}">Delete</button>
  `;
}

async function loadInspections() {
  const tbody = document.getElementById("inspections-body");
  const emptyState = document.getElementById("empty-state");

  try {
    const inspections = await apiFetch("/api/inspections");
    currentInspections = inspections;
    await buildLookups();
    populateManualProjectDropdown();

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

loadUser();
loadInspections();
