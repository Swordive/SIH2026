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
