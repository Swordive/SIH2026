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
    document.getElementById("user-role").textContent =
      ROLE_LABELS[me.role] || me.role;
  } catch (err) {
    // Token invalid/expired -> back to login
    clearToken();
    window.location.href = "login.html";
  }
}

function typeBadge(type) {
  return `<span class="badge ${type}">${type}</span>`;
}

async function loadProjects() {
  const tbody = document.getElementById("projects-body");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("project-count");

  try {
    const projects = await apiFetch("/api/projects");
    countEl.textContent = `${projects.length} total`;

    if (projects.length === 0) {
      emptyState.style.display = "block";
      return;
    }

    tbody.innerHTML = projects
      .map(
        (p) => `
      <tr>
        <td>${p.name}</td>
        <td>${typeBadge(p.entity_type)}</td>
        <td>${p.scheme_name || "—"}</td>
        <td>${p.address || "—"}</td>
        <td>${p.cctv_feed_url ? "Connected" : "Not configured"}</td>
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

loadUser();
loadProjects();
