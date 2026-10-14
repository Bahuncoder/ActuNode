import asyncio
import logging
import re
import shutil
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import vda5050
from app.config import settings
from app.live import hub
from app.mqtt_state import mqtt_bridge
from app.recorder import RecorderError, SessionRecorder, summarize
from app.replay import Replayer, ReplayError, scan_session
from app.session_store import (
    END_RECORD_RESERVE,
    UploadError,
    UploadWriter,
    check_upload,
    finish_upload,
    remove_upload_temps,
    storage_used,
)
from app.session_store import enforce_retention as _enforce_retention
from app.validate_session import SessionFormatError, validate_session

router = APIRouter(prefix="/api")
log = logging.getLogger("actunode.sessions")
# An upload that takes longer than this (a stalled client) is dropped and its temp file removed.
UPLOAD_TIMEOUT_S = 600
# One upload and one validation at a time: both are heavy, and a second one waits for nobody (429).
_upload_slot = asyncio.Semaphore(1)
_validate_slot = asyncio.Semaphore(1)
# Validation is CPU work: it gets its own single thread, so it cannot starve the default executor (WebSocket snapshots).
_VALIDATE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="validate")
VALIDATION_CACHE_ENTRIES = 16
_validation_cache: OrderedDict[tuple, dict] = OrderedDict()  # (session id, size, mtime_ns) -> report
MB = 1024 * 1024


def _sessions_changed() -> None:
    """Tell every open UI the session list is different (other tabs refresh it)."""
    hub.broadcast({"type": "sessions"})


def startup() -> None:
    """Housekeeping when the backend starts: leftovers of dead uploads, impossible limits, retention."""
    remove_upload_temps(recorder.directory)
    total = settings.sessions_max_total_mb
    if 0 < total < settings.max_session_mb:
        # Carry on: retention still protects the session being recorded, but a single full-size session
        # does not fit, so storage may stay over the total until one is deleted.
        log.warning(
            "ACTUNODE_SESSIONS_MAX_TOTAL_MB (%d) is smaller than ACTUNODE_MAX_SESSION_MB (%g): "
            "one full-size session will not fit in the total",
            total,
            settings.max_session_mb,
        )
    enforce_retention()


def enforce_retention(now: datetime | None = None, protect: tuple[str, ...] = ()) -> list[str]:
    """Apply the retention settings, never touching the session being recorded or replayed, nor those in
    `protect` (a recording that has only just stopped) (D-41)."""
    protected = set(protect)
    if current := recorder.status():
        protected.add(current["sessionId"])
    if replayer.running and (replay := replayer.status()):
        protected.add(replay["sessionId"])
    try:
        deleted = _enforce_retention(
            recorder.directory, settings.sessions_keep_days, settings.sessions_max_total_mb, protected, now
        )
    except OSError:
        log.exception("Retention failed")
        return []
    if deleted:
        _sessions_changed()
    return deleted


def _recording_stopped(status: dict, reason: str) -> None:
    """The recorder stopped by itself (size limit or write error): tell the UI."""
    hub.broadcast({"type": "recording", "recording": None, "stoppedReason": reason, "stopped": status})
    _sessions_changed()
    enforce_retention(protect=(status["sessionId"],))


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
    # Stamp each message with the time it is sent again, for a fleet manager that drops stale state (D-48).
    current_time: bool = False


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


@router.get("/sessions/storage")
def session_storage() -> dict:
    used, count = storage_used(recorder.directory)
    return {
        "keepDays": settings.sessions_keep_days,
        "maxTotalMb": settings.sessions_max_total_mb,
        "usedMb": round(used / (1024 * 1024), 1),
        "sessions": count,
    }


@router.post("/sessions/upload", status_code=201)
async def upload_session(request: Request, name: str | None = None) -> dict:
    """The request body is a session file. It is untrusted: size-capped while streaming, checked line by
    line, and stored under an id the server chooses (D-41). An upload never deletes other sessions: if the
    total would pass its limit it is refused (507)."""
    # A recording stopped at the size limit has its end record written past it.
    limit = int(settings.max_session_mb * MB) + END_RECORD_RESERVE
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"Session file is larger than {settings.max_session_mb:g} MB")
    if _upload_slot.locked():
        raise HTTPException(429, "An upload is already running")
    async with _upload_slot:
        directory = recorder.directory
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < 2 * limit:
            raise HTTPException(507, "Not enough free disk space for an upload")
        handle, temp_name = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=directory)
        temp = Path(temp_name)
        writer = UploadWriter(open(handle, "wb"), directory, lambda header: _chosen_name(name, header), _now)
        try:
            size = 0
            try:
                async with asyncio.timeout(UPLOAD_TIMEOUT_S):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, f"Session file is larger than {settings.max_session_mb:g} MB")
                        await asyncio.to_thread(writer.feed, chunk)
            except TimeoutError:
                raise HTTPException(408, "The upload took too long") from None
            finally:
                await asyncio.to_thread(writer.close)
            try:
                checked = await asyncio.to_thread(check_upload, temp)
            except UploadError as error:
                raise HTTPException(422, str(error)) from error
            if settings.sessions_max_total_mb:
                used, _ = await asyncio.to_thread(storage_used, directory)
                if used + size > settings.sessions_max_total_mb * MB:
                    raise HTTPException(507, "Session storage is full; delete sessions first")
            final = await asyncio.to_thread(finish_upload, temp, directory, writer, checked, _now)
            summary = await asyncio.to_thread(summarize, final)
        finally:
            temp.unlink(missing_ok=True)
    log.info("Uploaded session %s (%d bytes)", final.stem, size)
    _sessions_changed()
    return summary


def _now() -> datetime:
    return datetime.now(UTC)


def _chosen_name(query: str | None, header: dict | None) -> str:
    """The name in the new session's id: the query's, else the header's, else "upload"."""
    header_name = header.get("name") if header else None
    return _clean_name(query) or _clean_name(header_name if isinstance(header_name, str) else None) or "upload"


@router.post("/sessions/{session_id}/validate")
async def validate(session_id: str) -> dict:
    path = recorder.path_for(session_id)
    if path is None:
        raise HTTPException(404, f"Unknown session: {session_id}")
    current = recorder.status()
    if current and current["sessionId"] == session_id:
        raise HTTPException(409, "Cannot validate a session that is still being recorded")
    try:
        stat = path.stat()
    except OSError:
        raise HTTPException(404, f"Unknown session: {session_id}") from None
    key = (session_id, stat.st_size, stat.st_mtime_ns)
    if key in _validation_cache:
        _validation_cache.move_to_end(key)
        return _validation_cache[key]
    if _validate_slot.locked():
        raise HTTPException(429, "A validation is already running")
    async with _validate_slot:
        try:
            report = await asyncio.get_running_loop().run_in_executor(_VALIDATE_POOL, validate_session, path)
        except SessionFormatError as error:
            raise HTTPException(422, str(error)) from error
        except UnicodeDecodeError:
            raise HTTPException(422, "The session file is not UTF-8") from None
        except OSError:
            raise HTTPException(404, f"Unknown session: {session_id}") from None
    _validation_cache[key] = report
    while len(_validation_cache) > VALIDATION_CACHE_ENTRIES:
        _validation_cache.popitem(last=False)
    return report


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
    _sessions_changed()
    return status


@router.post("/recording/stop")
def stop_recording() -> dict:
    try:
        status = recorder.stop()
    except RecorderError as error:
        raise HTTPException(409, str(error)) from error
    hub.broadcast({"type": "recording", "recording": None})
    _sessions_changed()
    enforce_retention(protect=(status["sessionId"],))
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
    _sessions_changed()
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
        scan = await asyncio.to_thread(scan_session, path)
    except ReplayError as error:
        raise HTTPException(422, str(error)) from error

    keys = set(scan["robotIds"])
    if request.include_commands:  # failure injections reach the ActuNode simulator of that serial
        keys |= {
            robot["key"]
            for serial in scan["simSerials"]
            for robot in hub.robots_for(serial)
            if robot["manufacturer"] == vda5050.MANUFACTURER
        }
    live = sorted(key for key in keys if _is_live(key))
    if live:
        raise HTTPException(
            409,
            f"{', '.join(live)} {'is' if len(live) == 1 else 'are'} publishing live state; "
            "stop the simulator before replaying so live and replayed messages do not mix",
        )

    try:
        return replayer.start(
            session_id, path, scan, request.speed, request.include_commands, current_time=request.current_time
        )
    except ReplayError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/replay/stop")
def stop_replay() -> dict:
    try:
        replayer.stop()
    except ReplayError as error:
        raise HTTPException(409, str(error)) from error
    return {"stopping": True}


def _is_live(key: str) -> bool:
    """Is the robot with exactly this key ("<major>/<manufacturer>/<serial>") publishing state now?"""
    # Only state messages count: connection messages are retained by the broker
    # and re-delivered on every reconnect, long after a robot has gone.
    seen = [
        robot["lastStateAt"]
        for robot in hub.robots_for(key.rsplit("/", 1)[-1])
        if robot["key"] == key and robot.get("lastStateAt")
    ]
    if not seen:
        return False
    last_seen = max(datetime.fromisoformat(at) for at in seen)
    if replayer.ended_at and last_seen <= replayer.ended_at + REPLAY_ECHO:
        return False  # the last thing we heard came from a replay
    return datetime.now(UTC) - last_seen < LIVE_WINDOW
