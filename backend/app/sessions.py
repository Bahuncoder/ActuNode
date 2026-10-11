import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.live import hub
from app.mqtt_state import mqtt_bridge
from app.recorder import RecorderError, SessionRecorder
from app.replay import Replayer, ReplayError, scan_session

router = APIRouter(prefix="/api")


def _recording_stopped(status: dict, reason: str) -> None:
    """The recorder stopped by itself (size limit or write error): tell the UI."""
    hub.broadcast({"type": "recording", "recording": None, "stoppedReason": reason, "stopped": status})


recorder = SessionRecorder(
    settings.sessions_dir,
    max_bytes=int(settings.max_session_mb * 1024 * 1024),
    on_stopped=_recording_stopped,
)
hub.add_listener(recorder.record)

replayer = Replayer(
    publish=lambda topic, payload: mqtt_bridge.publish(topic, payload, qos=0),
    on_status=lambda status: hub.broadcast({"type": "replay", "replay": status}),
)

# A robot whose state arrived this recently is treated as live (the simulator publishes every second).
LIVE_WINDOW = timedelta(seconds=3)
# Messages published by a replay can still be arriving just after it ends.
REPLAY_ECHO = timedelta(seconds=0.5)


class ReplayRequest(BaseModel):
    speed: float = Field(default=1.0, ge=0.1, le=20)
    include_commands: bool = False


class StartRequest(BaseModel):
    name: str | None = Field(default=None, max_length=40, examples=["p1042-blocked-aisle"])


def _clean_name(name: str | None) -> str | None:
    """Session names end up in file names: keep letters, digits, - and _."""
    if not name:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
    return cleaned[:40] or None


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return recorder.list_sessions()


@router.get("/recording")
def recording_status() -> dict:
    return {"recording": recorder.status()}


@router.post("/recording/start", status_code=201)
def start_recording(request: StartRequest | None = None) -> dict:
    name = _clean_name(request.name if request else None)
    try:
        status = recorder.start(name, hub.snapshot()["robots"])
    except RecorderError as error:
        raise HTTPException(409, str(error)) from error
    hub.broadcast({"type": "recording", "recording": status})
    return status


@router.post("/recording/stop")
def stop_recording() -> dict:
    try:
        status = recorder.stop()
    except RecorderError as error:
        raise HTTPException(409, str(error)) from error
    hub.broadcast({"type": "recording", "recording": None})
    return status


@router.get("/sessions/{session_id}/download")
def download_session(session_id: str) -> FileResponse:
    path = recorder.path_for(session_id)
    if path is None:
        raise HTTPException(404, f"Unknown session: {session_id}")
    return FileResponse(path, media_type="application/x-ndjson", filename=path.name)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> Response:
    path = recorder.path_for(session_id)
    if path is None:
        raise HTTPException(404, f"Unknown session: {session_id}")
    current = recorder.status()
    if current and current["sessionId"] == session_id:
        raise HTTPException(409, "Cannot delete a session that is still being recorded")
    replay = replayer.status()
    if replayer.running and replay and replay["sessionId"] == session_id:
        raise HTTPException(409, "Cannot delete a session while it is being replayed")
    path.unlink()
    return Response(status_code=204)


@router.get("/replay")
def replay_status() -> dict:
    return {"replay": replayer.status()}


@router.post("/sessions/{session_id}/replay", status_code=202)
async def start_replay(session_id: str, request: ReplayRequest | None = None) -> dict:
    request = request or ReplayRequest()
    path = recorder.path_for(session_id)
    if path is None:
        raise HTTPException(404, f"Unknown session: {session_id}")
    current = recorder.status()
    if current and current["sessionId"] == session_id:
        raise HTTPException(409, "Cannot replay a session that is still being recorded")
    if not mqtt_bridge.connected:
        raise HTTPException(503, "MQTT broker is not connected")

    try:
        scan = scan_session(path)
    except ReplayError as error:
        raise HTTPException(422, str(error)) from error

    live = sorted(robot_id for robot_id in scan["robotIds"] if _is_live(robot_id))
    if live:
        raise HTTPException(
            409,
            f"{', '.join(live)} {'is' if len(live) == 1 else 'are'} publishing live state; "
            "stop the simulator before replaying so live and replayed messages do not mix",
        )

    try:
        return replayer.start(session_id, path, scan, request.speed, request.include_commands)
    except ReplayError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/replay/stop")
def stop_replay() -> dict:
    try:
        replayer.stop()
    except ReplayError as error:
        raise HTTPException(409, str(error)) from error
    return {"stopping": True}


def _is_live(robot_id: str) -> bool:
    # Only state messages count: connection messages are retained by the broker
    # and re-delivered on every reconnect, long after a robot has gone.
    seen = [robot["lastStateAt"] for robot in hub.robots_for(robot_id) if robot.get("lastStateAt")]
    if not seen:
        return False
    last_seen = max(datetime.fromisoformat(at) for at in seen)
    if replayer.ended_at and last_seen <= replayer.ended_at + REPLAY_ECHO:
        return False  # the last thing we heard came from a replay
    return datetime.now(UTC) - last_seen < LIVE_WINDOW
