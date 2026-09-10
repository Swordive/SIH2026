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
    return me;
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
    return null;
  }
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}

function roleBadge(role) {
  return `<span class="badge ${role}">${ROLE_LABELS[role] || role}</span>`;
}

function statusBadge(isActive) {
  return isActive
    ? `<span class="badge status-active">Active</span>`
    : `<span class="badge status-inactive">Inactive</span>`;
}

async function loadUsers() {
  const tbody = document.getElementById("users-body");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("user-count");
  const errorBox = document.getElementById("users-error");

  try {
    // GET /api/users is admin/department_official only server-side --
    // everyone else gets a 403, handled below by showing the
    // restricted-access state instead of the table.
    const users = await apiFetch("/api/users");
    countEl.textContent = `${users.length} total`;

    if (users.length === 0) {
      emptyState.style.display = "block";
      tbody.innerHTML = "";
      return;
    }
    emptyState.style.display = "none";

    tbody.innerHTML = users
      .map(
        (u) => `
      <tr>
        <td>${u.full_name}</td>
        <td>${u.email}</td>
        <td>${roleBadge(u.role)}</td>
        <td>${u.organization || "—"}</td>
        <td>${statusBadge(u.is_active)}</td>
        <td>${formatDate(u.created_at)}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    document.querySelector(".card").style.display = "none";
    document.getElementById("add-user-link").style.display = "none";
    countEl.textContent = "";
    document.getElementById("denied-state").style.display = "block";
  }
}

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

loadUser();
loadUsers();
