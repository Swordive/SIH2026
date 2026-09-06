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

function setStat(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? 0;
}

async function loadStats() {
  const errorBox = document.getElementById("dashboard-error");
  try {
    const stats = await apiFetch("/api/dashboard");

    setStat("stat-total-projects", stats.total_projects);
    setStat("stat-live-feeds", stats.projects_with_live_feed);
    setStat("stat-active-users", stats.active_users);
    setStat("stat-total-inspections", stats.total_inspections);
    setStat("stat-pending", stats.pending_inspections);
    setStat("stat-in-progress", stats.in_progress_inspections);
    setStat("stat-completed", stats.completed_inspections);
    setStat("stat-missed", stats.missed_inspections);

    document.getElementById("last-updated").textContent =
      `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  }
}

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

loadUser();
loadStats();
