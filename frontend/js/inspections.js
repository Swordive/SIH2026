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

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
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

  const projectMap = Object.fromEntries(projects.map((p) => [p.id, p.name]));
  const userMap = Object.fromEntries(users.map((u) => [u.id, u.full_name]));
  return { projectMap, userMap };
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

async function loadInspections() {
  const tbody = document.getElementById("inspections-body");
  const emptyState = document.getElementById("empty-state");

  try {
    const [inspections, { projectMap, userMap }] = await Promise.all([
      apiFetch("/api/inspections"),
      buildLookups(),
    ]);

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
      ? `Assigned ${created.length} new inspection${created.length === 1 ? "" : "s"}.`
      : "No projects were due for inspection right now.";
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

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

loadUser();
loadInspections();