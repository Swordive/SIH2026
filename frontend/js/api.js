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

/**
 * Same-origin-by-default convention as API_BASE above, but for
 * WebSocket URLs (ws:// or wss://, matching the page's own protocol).
 */
function wsBase() {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws");
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

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
 * A plain fetch() has no timeout: if the server (or the DB it talks
 * to) never sends a response -- host unreachable, connection
 * silently dropped instead of refused, backend deadlocked -- the
 * promise just never settles, and a caller like login.js is stuck
 * showing "Signing in..." forever with nothing to catch. This
 * wraps fetch() with an AbortController-based ceiling so every
 * request either succeeds, fails with the server's actual error, or
 * fails with a clear "the server didn't respond in time" message --
 * never hangs indefinitely.
 */
const DEFAULT_TIMEOUT_MS = 20000;

async function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        "The server didn't respond in time. It may be down, waking up from sleep, " +
        "or unable to reach its database — try again in a moment."
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
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

  const res = await fetchWithTimeout(`${API_BASE}${path}`, {
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

/**
 * apiUploadForm: multipart POST with a mix of plain fields and files
 * (e.g. the mandatory check-in: latitude/longitude fields plus a
 * selfie photo, all required by the backend in one request).
 * Deliberately does NOT set a Content-Type header -- the browser has
 * to set it itself with the multipart boundary, which it only does
 * when it builds the body.
 */
async function apiUploadForm(path, fields) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const formData = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    formData.append(key, value);
  }

  const res = await fetchWithTimeout(
    `${API_BASE}${path}`,
    { method: "POST", headers, body: formData },
    // Photo uploads (esp. evidence analysis) legitimately take longer
    // than a plain JSON call -- give this one more room before it's
    // treated as hung.
    60000
  );

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }

  return res.json();
}

/**
 * PMU inspectors carry out unannounced, independent visits -- being
 * able to preview a site's live CCTV feed beforehand (or during a
 * visit) would let them time arrivals or coordinate with site staff
 * off-camera, defeating the point of an unannounced check. Every
 * page's loadUser() calls this once the role is known; the actual
 * page-level enforcement lives in live-monitoring.js, since hiding a
 * nav link alone doesn't stop someone typing the URL directly.
 */
function hideLiveMonitoringNavIfInspector(role) {
  if (role !== "pmu_inspector") return;
  const link = document.querySelector('.sidebar nav a[href="live-monitoring.html"]');
  if (link) link.style.display = "none";
}

// Login uses OAuth2PasswordRequestForm on the backend, which expects
// x-www-form-urlencoded body with "username" + "password" fields.
async function login(email, password) {
  const params = new URLSearchParams();
  params.set("username", email);
  params.set("password", password);

  const res = await fetchWithTimeout(`${API_BASE}/api/auth/login`, {
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
