import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.live import hub
from app.recorder import RecorderError, SessionRecorder

router = APIRouter(prefix="/api")

recorder = SessionRecorder(settings.sessions_dir)
hub.add_listener(recorder.record)


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
        raise HTTPException(409, str(error))
    hub.broadcast({"type": "recording", "recording": status})
    return status


@router.post("/recording/stop")
def stop_recording() -> dict:
    try:
        status = recorder.stop()
    except RecorderError as error:
        raise HTTPException(409, str(error))
    hub.broadcast({"type": "recording", "recording": None})
    return status


@router.get("/sessions/{session_id}/download")
def download_session(session_id: str) -> FileResponse:
    path = recorder.path_for(session_id)
    if path is None:
        raise HTTPException(404, f"Unknown session: {session_id}")
    return FileResponse(path, media_type="application/x-ndjson", filename=path.name)
