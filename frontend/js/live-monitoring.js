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

    const liveMonitoringLink = document.querySelector('a[href="live-monitoring.html"]');
    if (liveMonitoringLink && me.role !== "admin") {
      liveMonitoringLink.style.display = "none";
    }
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
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

/**
 * Builds the static card markup only -- does NOT attach any video
 * source yet. Returns both the card (to insert into the grid) and
 * the inner videoWrap element (to attach playback to afterward, once
 * the card is actually in the document).
 */
function buildFeedCard(project) {
  const card = document.createElement("div");
  card.className = "feed-card";

  const videoWrap = document.createElement("div");
  videoWrap.className = "feed-video-wrap";

  if (project.cctv_feed_url) {
    const badge = document.createElement("div");
    badge.className = "live-badge";
    badge.innerHTML = `<span class="dot"></span> LIVE`;
    videoWrap.appendChild(badge);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "feed-placeholder";
    placeholder.textContent = "No CCTV feed configured for this project";
    videoWrap.appendChild(placeholder);
  }

  const info = document.createElement("div");
  info.className = "feed-info";
  info.innerHTML = `
    <h3>${project.name}</h3>
    <p>${project.address || "No address on file"}</p>
  `;

  card.appendChild(videoWrap);
  card.appendChild(info);
  return { card, videoWrap };
}

async function loadFeeds() {
  const grid = document.getElementById("feed-grid");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("feed-count");

  try {
    // Admin-only endpoint -- returns 403 for every other role. Live
    // camera feeds are restricted to admins, unlike general project
    // info (GET /api/projects), which more roles can see.
    const projects = await apiFetch("/api/projects/cctv-feeds");
    const withFeeds = projects.filter((p) => p.cctv_feed_url);

    countEl.textContent = `${withFeeds.length} of ${projects.length} projects have a live feed`;

    if (projects.length === 0) {
      emptyState.style.display = "block";
      return;
    }

    // Show projects with feeds first, then the ones without (as
    // placeholders) so officials can see coverage gaps at a glance.
    const ordered = [...withFeeds, ...projects.filter((p) => !p.cctv_feed_url)];

    // Step 1: build and insert all cards into the DOM first.
    const built = ordered.map((project) => {
      const { card, videoWrap } = buildFeedCard(project);
      grid.appendChild(card);
      return { project, videoWrap };
    });

    // Step 2: now that everything is actually on the page, attach
    // playback. This ordering is what fixes autoplay reliably
    // starting.
    built.forEach(({ project, videoWrap }) => {
      if (project.cctv_feed_url) {
        attachFeed(videoWrap, project.cctv_feed_url);
      }
    });
  } catch (err) {
    // A 403 here means the signed-in user isn't an admin -- live
    // monitoring is admin-only. Show a clear message instead of a
    // blank/broken page.
    emptyState.style.display = "block";
    emptyState.innerHTML = `
      <h3>Access restricted</h3>
      <p>${err.message.includes("permission") ? "Live camera monitoring is available to administrators only." : err.message}</p>
    `;
    countEl.textContent = "";
  }
}

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

loadUser();
loadFeeds();
