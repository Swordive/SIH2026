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
    return me;
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
    return null;
  }
}

/**
 * Attaches a playable feed to the given <video> element based on the
 * URL shape. Real CCTV integrations typically expose an HLS (.m3u8)
 * stream via an RTSP-to-web restreamer (e.g. MediaMTX) -- that's the
 * primary path here. YouTube links get an iframe fallback since some
 * teams demo with a public live stream during testing. Anything else
 * is treated as a direct video source (mp4/webm).
 *
 * IMPORTANT: call this only after `container` is already attached to
 * the document. Some browsers won't reliably start playback (via
 * MediaSource/hls.js in particular) on a <video> that's still
 * detached, which is a common cause of "loads metadata but never
 * actually plays."
 */
function attachFeed(container, url) {
  const isYouTube = /youtube\.com|youtu\.be/.test(url);
  const isHls = url.trim().toLowerCase().endsWith(".m3u8");

  if (isYouTube) {
    const embedUrl = url
      .replace("watch?v=", "embed/")
      .replace("youtu.be/", "youtube.com/embed/");
    const iframe = document.createElement("iframe");
    iframe.src = embedUrl;
    iframe.allow = "autoplay; encrypted-media";
    iframe.allowFullscreen = true;
    container.appendChild(iframe);
    return;
  }

  const video = document.createElement("video");
  video.muted = true;
  video.setAttribute("muted", ""); // some browsers check the markup attribute, not just the property
  video.autoplay = true;
  video.playsInline = true;
  video.controls = true;
  container.appendChild(video);

  const tryPlay = () => {
    const p = video.play();
    if (p && typeof p.catch === "function") {
      p.catch((err) => {
        console.warn("Autoplay blocked or playback failed:", err);
        // Controls are still visible so the official can hit play manually.
      });
    }
  };

  if (isHls && window.Hls && Hls.isSupported()) {
    const hls = new Hls();
    hls.loadSource(url);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, tryPlay);
    hls.on(Hls.Events.ERROR, (event, data) => {
      if (data.fatal) console.error("HLS fatal error:", data);
    });
  } else if (isHls && video.canPlayType("application/vnd.apple.mpegurl")) {
    // Safari plays HLS natively, no hls.js needed
    video.src = url;
    video.addEventListener("loadedmetadata", tryPlay);
  } else {
    // Direct video source (mp4/webm) or a browser that can't do HLS
    video.src = url;
    video.addEventListener("loadedmetadata", tryPlay);
  }
}

const TYPE_LABELS = {
  surprise: "Surprise visit",
  scheduled: "Scheduled inspection",
  vc_random: "Random VC check-in",
};

const STATUS_LABELS = {
  pending: "Pending",
  in_progress: "In progress",
};

// Inspections in these statuses are the ones worth watching live --
// not yet completed and not missed. ("in_progress" isn't set anywhere
// in the backend yet, but it's included here so this keeps working
// once that transition gets added.)
const ACTIVE_INSPECTION_STATUSES = ["pending", "in_progress"];

/**
 * Builds the static card markup only -- does NOT attach any video
 * source yet. Returns both the card (to insert into the grid) and
 * the inner videoWrap element (to attach playback to afterward, once
 * the card is actually in the document). One card per INSPECTION
 * (assignment), not per project -- two active inspections against
 * the same project, each with their own camera, get two cards.
 */
function buildFeedCard(project, inspection) {
  const card = document.createElement("div");
  card.className = "feed-card";

  const videoWrap = document.createElement("div");
  videoWrap.className = "feed-video-wrap";

  if (inspection.cctv_feed_url) {
    const badge = document.createElement("div");
    badge.className = "live-badge";
    badge.innerHTML = `<span class="dot"></span> LIVE`;
    videoWrap.appendChild(badge);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "feed-placeholder";
    placeholder.textContent = "No CCTV feed configured for this assignment";
    videoWrap.appendChild(placeholder);
  }

  const info = document.createElement("div");
  info.className = "feed-info";
  info.innerHTML = `
    <h3>${project ? project.name : "Unknown project"}</h3>
    <p>${(project && project.address) || "No address on file"}</p>
    <p>${TYPE_LABELS[inspection.inspection_type] || inspection.inspection_type} · ${
    STATUS_LABELS[inspection.status] || inspection.status
  }${inspection.scheduled_at ? " · " + new Date(inspection.scheduled_at).toLocaleString() : " · not yet scheduled"}</p>
  `;

  card.appendChild(videoWrap);
  card.appendChild(info);
  return { card, videoWrap };
}

async function loadFeeds() {
  const grid = document.getElementById("feed-grid");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("feed-count");

  // Alerts on the dashboard link here with ?project=<id> so an
  // official can jump straight to that project's live feed(s) to
  // review footage before deciding whether to resolve the alert.
  const params = new URLSearchParams(window.location.search);
  const filterProjectId = params.get("project");

  try {
    // /api/inspections is scoped server-side per role already (a PMU
    // inspector only ever gets their own assigned inspections back;
    // everyone else gets the full list), so this page just follows
    // that -- no separate admin-only endpoint needed now that the
    // feed lives on the inspection rather than the project.
    const [projects, inspections] = await Promise.all([
      apiFetch("/api/projects"),
      apiFetch("/api/inspections"),
    ]);

    const projectMap = Object.fromEntries(projects.map((p) => [p.id, p]));

    // One card per active inspection -- different assignments (even
    // against the same project) show up as separate feeds.
    let activeInspections = inspections.filter((i) =>
      ACTIVE_INSPECTION_STATUSES.includes(i.status)
    );

    if (filterProjectId) {
      activeInspections = activeInspections.filter((i) => i.project_id === filterProjectId);
      const projectName = projectMap[filterProjectId]?.name || "this project";
      document.querySelector("header h1").textContent = `Live Monitoring — ${projectName}`;
    }

    const withFeeds = activeInspections.filter((i) => i.cctv_feed_url);
    countEl.textContent = `${withFeeds.length} of ${activeInspections.length} active assignments have a live feed`;

    if (activeInspections.length === 0) {
      emptyState.style.display = "block";
      if (filterProjectId) {
        emptyState.innerHTML =
          "<h3>No active feed for this project</h3><p>There's no inspection currently in progress for this project with a CCTV feed attached.</p>";
      }
      return;
    }
    emptyState.style.display = "none";

    // Show assignments with feeds first, then the ones without (as
    // placeholders) so officials can see coverage gaps at a glance.
    const ordered = [...withFeeds, ...activeInspections.filter((i) => !i.cctv_feed_url)];

    // Step 1: build and insert all cards into the DOM first.
    const built = ordered.map((inspection) => {
      const { card, videoWrap } = buildFeedCard(projectMap[inspection.project_id], inspection);
      grid.appendChild(card);
      return { inspection, videoWrap };
    });

    // Step 2: now that everything is actually on the page, attach
    // playback. This ordering is what fixes autoplay reliably
    // starting.
    built.forEach(({ inspection, videoWrap }) => {
      if (inspection.cctv_feed_url) {
        attachFeed(videoWrap, inspection.cctv_feed_url);
      }
    });
  } catch (err) {
    emptyState.style.display = "block";
    emptyState.innerHTML = `<h3>Couldn't load feeds</h3><p>${err.message}</p>`;
    countEl.textContent = "";
  }
}

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

(async () => {
  const me = await loadUser();
  if (!me) return;

  if (me.role === "pmu_inspector") {
    document.getElementById("restricted-state").style.display = "block";
    document.getElementById("feed-count").textContent = "";
    return;
  }

  loadFeeds();
})();
