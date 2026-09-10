if (!getToken()) {
  window.location.href = "login.html";
}

const ROLE_LABELS = {
  admin: "Administrator",
  department_official: "Department Official",
  pmu_inspector: "PMU Inspector",
  project_incharge: "Project Incharge",
};

// Public STUN server, used only so each browser can discover its own
// public address for ICE -- no call audio/video/metadata goes through
// it. The signaling relay itself (see backend app/api/routes/vc.py)
// is fully self-hosted.
const ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];

const params = new URLSearchParams(window.location.search);
const inspectionId = params.get("inspection");

let ws = null;
let myPeerId = null;
let localStream = null;
const peerConnections = new Map(); // peer_id -> RTCPeerConnection
const peerInfo = new Map(); // peer_id -> { name, role }

const statusEl = document.getElementById("vc-status");
const grid = document.getElementById("vc-grid");
const roomEl = document.getElementById("vc-room");
const deniedEl = document.getElementById("vc-denied");
const deniedMessageEl = document.getElementById("vc-denied-message");

function setStatus(text) {
  statusEl.textContent = text;
}

function showDenied(message) {
  roomEl.style.display = "none";
  deniedEl.style.display = "block";
  if (message) deniedMessageEl.textContent = message;
  setStatus("");
}

function tileFor(peerId) {
  let tile = document.getElementById(`vc-tile-${peerId}`);
  if (!tile) {
    tile = document.createElement("div");
    tile.className = "vc-tile";
    tile.id = `vc-tile-${peerId}`;

    const video = document.createElement("video");
    video.autoplay = true;
    video.playsInline = true;
    tile.appendChild(video);

    const label = document.createElement("span");
    label.className = "vc-tile-label";
    const info = peerInfo.get(peerId);
    label.textContent = info ? `${info.name} (${ROLE_LABELS[info.role] || info.role})` : "Participant";
    tile.appendChild(label);

    grid.appendChild(tile);
  }
  return tile;
}

function removeTile(peerId) {
  const tile = document.getElementById(`vc-tile-${peerId}`);
  if (tile) tile.remove();
}

function createPeerConnection(peerId) {
  const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

  if (localStream) {
    localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
  }

  pc.onicecandidate = (event) => {
    if (event.candidate) {
      sendSignal({ type: "candidate", to: peerId, payload: event.candidate });
    }
  };

  pc.ontrack = (event) => {
    const tile = tileFor(peerId);
    const video = tile.querySelector("video");
    if (video.srcObject !== event.streams[0]) {
      video.srcObject = event.streams[0];
    }
  };

  peerConnections.set(peerId, pc);
  return pc;
}

function sendSignal(message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}

async function handleWelcome(message) {
  myPeerId = message.peer_id;
  setStatus(message.peers.length === 0 ? "Waiting for the other side to join…" : "Connecting to the call…");

  // We're the new joiner: create a (receive-only-for-now) connection
  // per existing peer and wait for their offer, rather than racing
  // them to send one ourselves.
  for (const peer of message.peers) {
    peerInfo.set(peer.peer_id, { name: peer.name, role: peer.role });
    createPeerConnection(peer.peer_id);
  }
}

async function handlePeerJoined(message) {
  peerInfo.set(message.peer_id, { name: message.name, role: message.role });
  setStatus("Connecting to the call…");

  // We were already in the room: we make the offer to the new joiner.
  const pc = createPeerConnection(message.peer_id);
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  sendSignal({ type: "offer", to: message.peer_id, payload: offer });
}

async function handleOffer(message) {
  const pc = peerConnections.get(message.from) || createPeerConnection(message.from);
  await pc.setRemoteDescription(new RTCSessionDescription(message.payload));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  sendSignal({ type: "answer", to: message.from, payload: answer });
  setStatus("On the call");
}

async function handleAnswer(message) {
  const pc = peerConnections.get(message.from);
  if (!pc) return;
  await pc.setRemoteDescription(new RTCSessionDescription(message.payload));
  setStatus("On the call");
}

async function handleCandidate(message) {
  const pc = peerConnections.get(message.from);
  if (!pc) return;
  try {
    await pc.addIceCandidate(new RTCIceCandidate(message.payload));
  } catch (err) {
    console.warn("Failed to add ICE candidate", err);
  }
}

function handlePeerLeft(message) {
  const pc = peerConnections.get(message.peer_id);
  if (pc) {
    pc.close();
    peerConnections.delete(message.peer_id);
  }
  peerInfo.delete(message.peer_id);
  removeTile(message.peer_id);
  if (peerConnections.size === 0) {
    setStatus("Waiting for the other side to join…");
  }
}

function connectSignaling() {
  const token = getToken();
  ws = new WebSocket(`${wsBase()}/ws/vc/${inspectionId}?token=${encodeURIComponent(token)}`);

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    switch (message.type) {
      case "welcome":
        handleWelcome(message);
        break;
      case "peer-joined":
        handlePeerJoined(message);
        break;
      case "offer":
        handleOffer(message);
        break;
      case "answer":
        handleAnswer(message);
        break;
      case "candidate":
        handleCandidate(message);
        break;
      case "peer-left":
        handlePeerLeft(message);
        break;
    }
  };

  ws.onclose = (event) => {
    // Matches the close codes the backend uses to reject a join --
    // see app/api/routes/vc.py.
    if (event.code === 4401 || event.code === 4403) {
      showDenied("You don't have permission to join this call.");
    } else if (event.code === 4404) {
      showDenied("This inspection couldn't be found.");
    } else if (event.code === 4409) {
      showDenied("This call already has the maximum number of participants.");
    } else if (peerConnections.size === 0 && myPeerId === null) {
      showDenied("Could not connect to the call.");
    } else {
      setStatus("Call ended.");
    }
  };
}

async function init() {
  if (!inspectionId) {
    showDenied("No inspection specified.");
    return;
  }

  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("user-name").textContent = me.full_name;
    document.getElementById("user-role").textContent = ROLE_LABELS[me.role] || me.role;
  } catch (err) {
    clearToken();
    window.location.href = "login.html";
    return;
  }

  try {
    const inspection = await apiFetch(`/api/inspections/${inspectionId}`);
    const projects = await apiFetch("/api/projects");
    const project = projects.find((p) => p.id === inspection.project_id);
    document.getElementById("vc-project-name").textContent = project ? project.name : "";
  } catch (err) {
    showDenied("Could not load this inspection.");
    return;
  }

  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  } catch (err) {
    showDenied("Camera/microphone access is required to join the call.");
    return;
  }

  document.getElementById("vc-local-video").srcObject = localStream;
  connectSignaling();
}

document.getElementById("vc-toggle-mic").addEventListener("click", (e) => {
  if (!localStream) return;
  const track = localStream.getAudioTracks()[0];
  if (!track) return;
  track.enabled = !track.enabled;
  e.target.textContent = track.enabled ? "Mute mic" : "Unmute mic";
});

document.getElementById("vc-toggle-cam").addEventListener("click", (e) => {
  if (!localStream) return;
  const track = localStream.getVideoTracks()[0];
  if (!track) return;
  track.enabled = !track.enabled;
  e.target.textContent = track.enabled ? "Turn off camera" : "Turn on camera";
});

document.getElementById("vc-leave").addEventListener("click", () => {
  peerConnections.forEach((pc) => pc.close());
  peerConnections.clear();
  if (localStream) localStream.getTracks().forEach((track) => track.stop());
  if (ws) ws.close();
  window.location.href = "inspections.html";
});

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  window.location.href = "login.html";
});

init();
