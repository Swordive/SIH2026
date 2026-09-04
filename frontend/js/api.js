// Central place for the backend base URL and auth-aware fetch helper.
// Change API_BASE if the backend isn't running on localhost:8000.
const API_BASE = "http://localhost:8000";

function getToken() {
  return localStorage.getItem("access_token");
}

function setToken(token) {
  localStorage.setItem("access_token", token);
}

function clearToken() {
  localStorage.removeItem("access_token");
}

/**
 * apiFetch: wraps fetch() with the API base URL, JSON handling,
 * and the bearer token (when present). Throws on non-2xx with the
 * server's error detail when available.
 */
async function apiFetch(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }

  if (res.status === 204) return null;
  return res.json();
}

// Login uses OAuth2PasswordRequestForm on the backend, which expects
// x-www-form-urlencoded body with "username" + "password" fields.
async function login(email, password) {
  const params = new URLSearchParams();
  params.set("username", email);
  params.set("password", password);

  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });

  if (!res.ok) {
    let detail = "Login failed";
    try {
      const data = await res.json();
      if (data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }

  const data = await res.json();
  setToken(data.access_token);
  return data;
}
