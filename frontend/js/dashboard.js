if (!getToken()) {
  window.location.href = "login.html";
}

const ROLE_LABELS = {
  admin: "Administrator",
  department_official: "Department Official",
  pmu_inspector: "PMU Inspector",
  project_incharge: "Project Incharge",
};

async function loadUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
    hideLiveMonitoringNavIfInspector(me.role);

    // Live Monitoring is now open to every role -- feeds live on
    // individual inspections and /api/inspections already scopes what
    // each role can see (a PMU inspector only ever gets their own
    // assigned inspections back), so there's nothing left to gate here.

    // PMU inspectors only see their own numbers -- the org-wide overview
    // cards (all projects, all active users) aren't "his statistics".
    if (me.role === "pmu_inspector") {
      document.getElementById("overview-title").textContent = "My inspections";
      document.getElementById("status-title").textContent = "My inspections by status";
      document.getElementById("label-total-projects").textContent = "Projects assigned to me";
      document.getElementById("label-live-feeds").textContent = "My assignments with a live CCTV feed";
      document.getElementById("label-total-inspections").textContent = "My total inspections";
      document.getElementById("card-active-users").style.display = "none";
    }

    // The Alerts panel mirrors GET/PATCH /api/alerts's own server-side
    // role check (admin + department_official only) -- everyone else
    // never sees the section at all rather than hitting a 403.
    if (me.role === "admin" || me.role === "department_official") {
      document.getElementById("alerts-title").style.display = "flex";
      document.getElementById("alerts-card").style.display = "block";
      await loadProjectsForAlerts();
      await loadAlerts();
    }
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
  }
}

function setStat(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? 0;
}

async function loadStats() {
  const errorBox = document.getElementById("dashboard-error");
  try {
    const stats = await apiFetch("/api/dashboard");

    setStat("stat-total-projects", stats.total_projects);
    setStat("stat-live-feeds", stats.inspections_with_live_feed);
    setStat("stat-active-users", stats.active_users);
    setStat("stat-total-inspections", stats.total_inspections);
    setStat("stat-pending", stats.pending_inspections);
    setStat("stat-in-progress", stats.in_progress_inspections);
    setStat("stat-completed", stats.completed_inspections);
    setStat("stat-missed", stats.missed_inspections);
    setStat("stat-flagged-attendance", stats.flagged_attendance_checks);

    document.getElementById("last-updated").textContent =
      `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  }
}

// ---- Alerts panel ----

let projectNameById = {};
let showUnresolvedOnly = true;

async function loadProjectsForAlerts() {
  try {
    const projects = await apiFetch("/api/projects");
    projectNameById = Object.fromEntries(projects.map((p) => [p.id, p.name]));
  } catch (err) {
    projectNameById = {};
  }
}

function severityBadge(severity) {
  const known = ["low", "medium", "high", "critical"];
  const cls = known.includes(severity) ? `severity-${severity}` : "severity-medium";
  return `<span class="badge ${cls}">${severity}</span>`;
}

function renderAlerts(alerts) {
  const list = document.getElementById("alerts-list");
  const empty = document.getElementById("alerts-empty");

  if (alerts.length === 0) {
    list.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";

  list.innerHTML = alerts
    .map(
      (a) => `
    <div class="alert-row ${a.resolved ? "resolved" : ""}">
      <div class="alert-main">
        <div class="alert-message">${a.message}</div>
        <div class="alert-meta">
          ${severityBadge(a.severity)}
          <span>${projectNameById[a.project_id] || a.project_id}</span>
          <span>·</span>
          <span>${new Date(a.created_at).toLocaleString()}</span>
        </div>
      </div>
      <div class="alert-actions">
        ${
          a.resolved
            ? `<span class="badge status-active">Resolved</span>`
            : `<button class="row-action" data-action="resolve" data-id="${a.id}">Mark resolved</button>`
        }
      </div>
    </div>`
    )
    .join("");
}

async function loadAlerts() {
  try {
    const alerts = await apiFetch(
      `/api/alerts?unresolved_only=${showUnresolvedOnly}`
    );
    renderAlerts(alerts);
  } catch (err) {
    // Role-gated at the call site above, so this should only fire on
    // a genuine network/server error -- fail quietly into the empty
    // state rather than breaking the rest of the dashboard.
    renderAlerts([]);
  }
}

document.getElementById("alerts-filter-toggle").addEventListener("click", (e) => {
  showUnresolvedOnly = !showUnresolvedOnly;
  e.target.classList.toggle("active", showUnresolvedOnly);
  e.target.textContent = showUnresolvedOnly ? "Unresolved only" : "Showing all";
  loadAlerts();
});

document.getElementById("alerts-list").addEventListener("click", async (e) => {
  const btn = e.target.closest('button[data-action="resolve"]');
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = "Resolving…";
  try {
    await apiFetch(`/api/alerts/${btn.dataset.id}/resolve`, { method: "PATCH" });
    await loadAlerts();
    await loadStats(); // unresolved_alerts count on the dashboard stats, if ever surfaced
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.textContent = "Mark resolved";
  }
});

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

loadUser();
loadStats();
