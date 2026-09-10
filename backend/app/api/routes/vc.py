"""
WebRTC signaling relay for "Random Video Conferencing (VC) connectivity
with Project Incharge/Staff/Beneficiaries" -- one room per inspection,
peers exchange SDP offers/answers and ICE candidates through this
relay, then talk directly to each other peer-to-peer (audio/video
never passes through this backend).

Self-hosted on purpose: no third-party video API/key, so it works the
same in an offline/air-gapped field deployment as in a demo. Browsers
still need a STUN server to discover their public address for ICE --
the frontend points at a public STUN server for that (see
video-call.js) -- but no media or call metadata goes through it.

Scaling note: rooms are held in an in-process dict, which is fine for
a single-worker deployment (matches how the rest of this hackathon
build runs) but would need a shared store (e.g. Redis pub/sub) instead
if ever run with multiple workers/processes, since WebSocket
connections aren't shared across them.
"""
import json
import uuid as uuid_lib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models.inspection import Inspection
from app.models.project import Project
from app.models.user import User, UserRole

router = APIRouter()

# _rooms[inspection_id][peer_id] = {"ws": WebSocket, "name": str, "role": str}
_rooms: dict[str, dict[str, dict]] = {}

MAX_PARTICIPANTS_PER_ROOM = 6


def _authenticate(token: str, db) -> User | None:
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if user is None or not user.is_active:
        return None
    return user


def _can_join(user: User, inspection: Inspection, project: Project | None) -> bool:
    """Admins and department officials can always sit in on a call --
    the same oversight freedom they already have everywhere else in
    this app. A PMU inspector can only join the call for their own
    assigned inspection; a project incharge can only join for a
    project they actually run. Everyone else is refused."""
    if user.role in (UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL):
        return True
    if user.role == UserRole.PMU_INSPECTOR:
        return inspection.inspector_id == user.id
    if user.role == UserRole.PROJECT_INCHARGE:
        return project is not None and project.incharge_id == user.id
    return False


@router.websocket("/ws/vc/{inspection_id}")
async def vc_signaling(websocket: WebSocket, inspection_id: str, token: str = Query(...)):
    db = SessionLocal()
    try:
        user = _authenticate(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

        try:
            inspection_uuid = uuid_lib.UUID(inspection_id)
        except ValueError:
            await websocket.close(code=4404)
            return

        inspection = (
            db.query(Inspection).filter(Inspection.id == inspection_uuid).first()
        )
        if inspection is None:
            await websocket.close(code=4404)
            return

        project = (
            db.query(Project).filter(Project.id == inspection.project_id).first()
        )

        if not _can_join(user, inspection, project):
            await websocket.close(code=4403)
            return

        room = _rooms.setdefault(inspection_id, {})
        if len(room) >= MAX_PARTICIPANTS_PER_ROOM:
            await websocket.close(code=4409)
            return

        user_name = user.full_name
        user_role = user.role.value
    finally:
        db.close()

    await websocket.accept()
    peer_id = str(uuid_lib.uuid4())
    room[peer_id] = {"ws": websocket, "name": user_name, "role": user_role}

    await websocket.send_json(
        {
            "type": "welcome",
            "peer_id": peer_id,
            "peers": [
                {"peer_id": pid, "name": info["name"], "role": info["role"]}
                for pid, info in room.items()
                if pid != peer_id
            ],
        }
    )

    for pid, info in room.items():
        if pid == peer_id:
            continue
        await info["ws"].send_json(
            {
                "type": "peer-joined",
                "peer_id": peer_id,
                "name": user_name,
                "role": user_role,
            }
        )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("type")
            target = message.get("to")
            if msg_type not in ("offer", "answer", "candidate") or not target:
                continue

            target_info = room.get(target)
            if target_info is None:
                continue

            await target_info["ws"].send_json(
                {"type": msg_type, "from": peer_id, "payload": message.get("payload")}
            )
    except WebSocketDisconnect:
        pass
    finally:
        room.pop(peer_id, None)
        for info in room.values():
            try:
                await info["ws"].send_json({"type": "peer-left", "peer_id": peer_id})
            except Exception:
                pass
        if not room:
            _rooms.pop(inspection_id, None)
