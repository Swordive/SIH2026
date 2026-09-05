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

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
    canManage = me.role === "admin" || me.role === "department_official";
    document.getElementById("run-assignment-btn").style.display = canManage
      ? "inline-block"
      : "none";
    document.getElementById("toggle-manual-form").style.display = canManage
      ? "inline-block"
      : "none";

    // Live camera monitoring is admin-only (enforced server-side too --
    // this just avoids showing a dead-end link to everyone else).
    const liveMonitoringLink = document.querySelector('a[href="live-monitoring.html"]');
    if (liveMonitoringLink && me.role !== "admin") {
      liveMonitoringLink.style.display = "none";
    }
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

function actionsCell(inspection) {
  if (!canManage) return "—";
  const assignLabel = inspection.inspector_id ? "Reassign" : "Assign";
  return `
    <button class="row-action" data-action="assign" data-id="${inspection.id}">${assignLabel}</button>
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
        <td>${i.inspector_id ? (userMap[i.inspector_id] || i.inspector_id) : "Unassigned"}</td>
        <td>${TYPE_LABELS[i.inspection_type] || i.inspection_type}</td>
        <td>${STATUS_LABELS[i.status] || i.status}</td>
        <td>${i.ai_assigned ? "AI / automation" : "Manual"}</td>
        <td>${formatDate(i.scheduled_at)}</td>
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

  manualSubmitBtn.disabled = true;
  manualSubmitBtn.textContent = "Adding…";

  try {
    await apiFetch(`/api/inspections/manual?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST",
    });
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

document.getElementById("inspections-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;

  const inspection = currentInspections.find((i) => i.id === btn.dataset.id);
  if (!inspection) return;

  if (btn.dataset.action === "assign") {
    openAssignForm(inspection);
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
