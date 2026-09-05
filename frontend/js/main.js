if (!getToken()) {
  window.location.href = "login.html";
}

const ROLE_LABELS = {
  admin: "Administrator",
  department_official: "Department Official",
  pmu_inspector: "PMU Inspector",
  project_incharge: "Project Incharge",
};

let currentProjects = [];
let canManageProjects = false;
let editingProjectId = null; // null = create mode, otherwise editing this project's id

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent =
      ROLE_LABELS[me.role] || me.role;

    // Only admins and department officials can create/edit/delete projects.
    canManageProjects = me.role === "admin" || me.role === "department_official";
    document.getElementById("toggle-add-form").style.display = canManageProjects
      ? "inline-block"
      : "none";

    // Live camera monitoring is admin-only (enforced server-side too --
    // this just avoids showing a dead-end link to everyone else).
    const liveMonitoringLink = document.querySelector('a[href="live-monitoring.html"]');
    if (liveMonitoringLink && me.role !== "admin") {
      liveMonitoringLink.style.display = "none";
    }
  } catch (err) {
    // Token invalid/expired -> back to login
    clearToken();
    window.location.href = "login.html";
  }
}

function typeBadge(type) {
  return `<span class="badge ${type}">${type}</span>`;
}

function actionsCell(project) {
  if (!canManageProjects) return "—";
  return `
    <button class="row-action" data-action="edit" data-id="${project.id}">Edit</button>
    <button class="row-action danger" data-action="delete" data-id="${project.id}">Delete</button>
  `;
}

async function loadProjects() {
  const tbody = document.getElementById("projects-body");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("project-count");

  try {
    const projects = await apiFetch("/api/projects");
    currentProjects = projects;
    countEl.textContent = `${projects.length} total`;

    if (projects.length === 0) {
      emptyState.style.display = "block";
      tbody.innerHTML = "";
      return;
    }
    emptyState.style.display = "none";

    tbody.innerHTML = projects
      .map(
        (p) => `
      <tr>
        <td>${p.name}</td>
        <td>${typeBadge(p.entity_type)}</td>
        <td>${p.scheme_name || "—"}</td>
        <td>${p.address || "—"}</td>
        <td>${p.cctv_feed_url ? "Connected" : "Not configured"}</td>
        <td>${actionsCell(p)}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    countEl.textContent = "Could not load projects";
  }
}

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

const toggleBtn = document.getElementById("toggle-add-form");
const cancelBtn = document.getElementById("cancel-add-form");
const addForm = document.getElementById("add-project-form");
const submitBtn = document.getElementById("add-project-submit");

function resetFormToCreateMode() {
  editingProjectId = null;
  addForm.reset();
  submitBtn.textContent = "Create project";
}

function openFormForCreate() {
  resetFormToCreateMode();
  addForm.classList.add("open");
}

function openFormForEdit(project) {
  editingProjectId = project.id;
  document.getElementById("p-name").value = project.name || "";
  document.getElementById("p-type").value = project.entity_type || "project";
  document.getElementById("p-scheme").value = project.scheme_name || "";
  document.getElementById("p-address").value = project.address || "";
  document.getElementById("p-cctv").value = project.cctv_feed_url || "";
  submitBtn.textContent = "Save changes";
  addForm.classList.add("open");
  addForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

toggleBtn.addEventListener("click", () => {
  if (addForm.classList.contains("open")) {
    addForm.classList.remove("open");
  } else {
    openFormForCreate();
  }
});

cancelBtn.addEventListener("click", () => {
  addForm.classList.remove("open");
  resetFormToCreateMode();
});

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("add-project-error");
  errorBox.style.display = "none";
  submitBtn.disabled = true;
  submitBtn.textContent = editingProjectId ? "Saving…" : "Creating…";

  const payload = {
    name: document.getElementById("p-name").value.trim(),
    entity_type: document.getElementById("p-type").value,
    scheme_name: document.getElementById("p-scheme").value.trim() || null,
    address: document.getElementById("p-address").value.trim() || null,
    cctv_feed_url: document.getElementById("p-cctv").value.trim() || null,
  };

  try {
    if (editingProjectId) {
      await apiFetch(`/api/projects/${editingProjectId}`, {
        method: "PATCH",
        body: payload,
      });
    } else {
      await apiFetch("/api/projects", { method: "POST", body: payload });
    }
    addForm.classList.remove("open");
    resetFormToCreateMode();
    await loadProjects();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = editingProjectId ? "Save changes" : "Create project";
  }
});

// Event delegation for per-row Edit/Delete buttons, since rows are
// re-rendered on every load.
document.getElementById("projects-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;

  const project = currentProjects.find((p) => p.id === btn.dataset.id);
  if (!project) return;

  if (btn.dataset.action === "edit") {
    openFormForEdit(project);
    return;
  }

  if (btn.dataset.action === "delete") {
    const confirmed = confirm(
      `Delete "${project.name}"? This also removes any inspections linked to it. This cannot be undone.`
    );
    if (!confirmed) return;

    btn.disabled = true;
    btn.textContent = "Deleting…";
    try {
      await apiFetch(`/api/projects/${project.id}`, { method: "DELETE" });
      if (editingProjectId === project.id) {
        addForm.classList.remove("open");
        resetFormToCreateMode();
      }
      await loadProjects();
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
      btn.textContent = "Delete";
    }
  }
});

loadUser();
loadProjects();
