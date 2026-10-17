"""Audit trail (D-56): who changed what in the lab, and when.

Every state-changing /api request by a known user is recorded (method other than GET/HEAD/OPTIONS), with the
answer's status, plus logins (also failed ones) and logouts. Routes add what the path does not say (robot,
failure, destination) through `request.state.audit`. Entries are JSON lines in a file next to the recordings
(ACTUNODE_AUDIT_FILE), rotated once at MAX_BYTES; the latest KEEP entries are also kept in memory for the API.
"""

import json
import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Query, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.security import LogThrottle

log = logging.getLogger("actunode.audit")
_write_failed_log = LogThrottle()

MAX_BYTES = 10 * 1024 * 1024
KEEP = 2000
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
NOT_BY_MIDDLEWARE = {"/api/login"}  # recorded by the login route itself (it knows whether the token matched)

# (method, path pattern) -> action name; the first match wins.
ACTIONS = [
    ("POST", r"/api/missions", "mission.send"),
    ("POST", r"/api/missions/[^/]+/cancel", "mission.cancel"),
    ("POST", r"/api/missions/[^/]+/extend", "mission.extend"),
    ("POST", r"/api/failures", "failure"),  # the route names inject or clear
    ("POST", r"/api/validation/reset", "validation.reset"),
    ("POST", r"/api/sessions/upload", "session.upload"),
    ("POST", r"/api/sessions/[^/]+/validate", "session.validate"),
    ("POST", r"/api/sessions/[^/]+/replay", "replay.start"),
    ("DELETE", r"/api/sessions/[^/]+", "session.delete"),
    ("POST", r"/api/recording/start", "recording.start"),
    ("POST", r"/api/recording/stop", "recording.stop"),
    ("POST", r"/api/replay/stop", "replay.stop"),
    ("POST", r"/api/logout", "logout"),
]
_ACTIONS = [(method, re.compile(pattern), name) for method, pattern, name in ACTIONS]


def action_for(method: str, path: str) -> str:
    for known_method, pattern, name in _ACTIONS:
        if method == known_method and pattern.fullmatch(path):
            return name
    return f"{method.lower()} {path[:100]}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AuditLog:
    def __init__(self):
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._recent: deque[dict] = deque(maxlen=KEEP)

    def configure(self, path: Path | None) -> None:
        with self._lock:
            self._path = path
            self._recent.clear()
            if path is None:
                return
            for source in (path.with_name(path.name + ".1"), path):
                try:
                    with source.open(encoding="utf-8", errors="replace") as file:
                        for line in file:
                            try:
                                entry = json.loads(line)
                            except ValueError:
                                continue  # a torn last line after a crash
                            if isinstance(entry, dict):
                                self._recent.append(entry)
                except FileNotFoundError:
                    pass

    def record(self, entry: dict) -> None:
        line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self._lock:
            self._recent.append(entry)
            if self._path is None:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                if self._path.exists() and self._path.stat().st_size >= MAX_BYTES:
                    self._path.replace(self._path.with_name(self._path.name + ".1"))
                with self._path.open("a", encoding="utf-8") as file:
                    file.write(line)
            except OSError as error:
                if (suppressed := _write_failed_log.allow()) is not None:
                    more = f" ({suppressed} more not logged)" if suppressed else ""
                    log.warning("Audit trail not written to %s: %s%s", self._path, error, more)

    def recent(self, limit: int, user: str | None = None, action: str | None = None) -> list[dict]:
        """Newest first; `action` matches a whole name or a prefix before a dot (`failure` finds both kinds)."""
        with self._lock:
            entries = list(self._recent)
        found = []
        for entry in reversed(entries):
            name = str(entry.get("action", ""))
            if user and entry.get("user") != user:
                continue
            if action and name != action and not name.startswith(action + "."):
                continue
            found.append(entry)
            if len(found) >= limit:
                break
        return found


trail = AuditLog()
trail.configure(settings.audit_file)


def _entry(request: Request, action: str, status: int) -> dict:
    from app.auth import _client  # auth imports this module

    user = getattr(request.state, "user", None)
    detail = getattr(request.state, "audit", None) or {}
    entry = {
        "at": _now(),
        "user": user.name if user else None,
        "role": user.role if user else None,
        "client": _client(request)[:100],
        "action": detail.get("action", action),
        "method": request.method,
        "path": request.url.path[:200],
        "status": status,
    }
    # Details come from request bodies, some before validation: bounded, so a junk value cannot bloat the trail.
    # They add to the core fields, never replace them (who, when, what answer).
    entry.update({key: _bounded(value) for key, value in detail.items() if key not in entry})
    entry["action"] = _bounded(entry["action"])
    return entry


def _bounded(value):
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:100]


def record_request(request: Request, action: str, status: int) -> None:
    trail.record(_entry(request, action, status))


class AuditTrail:
    """Records every state-changing /api request whose user is known (SessionGuard, inside this, sets it)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not path.startswith("/api")
            or scope.get("method") in SAFE_METHODS
            or path in NOT_BY_MIDDLEWARE
        ):
            await self.app(scope, receive, send)
            return
        status = 500  # unless a response starts

        async def watch(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watch)
        finally:
            request = Request(scope)
            if getattr(request.state, "user", None) is not None:
                trail.record(_entry(request, action_for(scope["method"], path), status))


router = APIRouter(prefix="/api")


@router.get("/audit")
def audit_entries(
    limit: int = Query(100, ge=1, le=500),
    user: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=64),
) -> dict:
    return {"entries": trail.recent(limit, user, action)}
