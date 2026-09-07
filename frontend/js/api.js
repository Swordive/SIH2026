// Central place for the backend base URL and auth-aware fetch helper.
//
// The backend serves the frontend itself (see main.py's StaticFiles
// mount) so that the whole app can be exposed through a single tunnel
// (ngrok/cloudflared) on one origin. Because of that, API_BASE should
// normally be relative/empty -- fetches then go to whatever origin the
// page was actually loaded from (localhost:8000, a tunnel URL, a
// deployed domain, doesn't matter).
//
// The one exception is local dev via a separate static file server
// (e.g. VS Code "Live Server" on port 5500) with the backend running
// standalone on 8000 -- that's the only case that needs an explicit
// cross-origin base, and it's also the only origin the backend's CORS
// config (see ALLOWED_ORIGINS in config.py) allows.
const API_BASE = window.location.port === "5500" ? "http://localhost:8000" : "";

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
