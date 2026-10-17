"""Record MQTT traffic to JSONL session files.

File layout, one JSON object per line:

    {"type": "session",  "formatVersion": 1, "sessionId", "name", "startedAt"}
    {"type": "snapshot", "robots": [...]}            latest robot states at start
    {"type": "message",  "t", "receivedAt", "topic", "retained", "payload", "issues"?}   (many)
    {"type": "end",      "endedAt", "messageCount", "reason"}  missing if the backend crashed

`t` is seconds since recording started. `payload` is the parsed JSON; a message
that was not valid JSON is stored as the raw string in `payloadRaw` instead.
`issues` (validator findings) is present only when the message had any. `rejected` (the rule's name:
invalid-json, non-finite-number, too-deep, payload-too-large) is present only when the live parse rules
rejected the payload; what is stored then is only display text (decoded with replacement characters, or a
1 KiB preview), so offline validation reads the rule from here instead of re-parsing.
`reason` says why recording ended: "stopped" (by the user or at shutdown), "sizeLimit", or
"writeError: ..." (e.g. disk full). Older files may lack it.
"""

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.session_records import (
    MESSAGE_LINE_BYTES,
    SNAPSHOT_LINE_BYTES,
    SNAPSHOT_ROBOT_BYTES,
    iter_records,
    parse_line,
)

log = logging.getLogger("actunode.recorder")

FORMAT_VERSION = 1
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
# Read at most this much from the end of a file to find its end record.
TAIL_BYTES = 64 * 1024
MAX_FIELD_CHARS = 200
SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(_[A-Za-z0-9_-]{1,40})?$")


def make_session_id(stamp: str, name: str | None, attempt: int = 1) -> str:
    """The one naming rule for recordings and uploads: the start time (to the second) and the name, then `_2`,
    `_3`, ... on later attempts, so two sessions started in the same second stay apart. The name is cut so the id
    always fits SESSION_ID."""
    suffix = f"_{attempt}" if attempt > 1 else ""
    if not name:
        return f"{stamp}{suffix}"
    return f"{stamp}_{name[: 40 - len(suffix)]}{suffix}"


def fit_snapshot(robots: list[dict]) -> list[dict]:
    """The robots that fit the snapshot line (SNAPSHOT_LINE_BYTES, each at most SNAPSHOT_ROBOT_BYTES): a reader
    parses that line whole, so what is written must stay within what is read (D2)."""
    fitted, used = [], 1024
    for robot in robots:
        size = len(json.dumps(robot, separators=(",", ":"), allow_nan=False)) + 1
        if size > SNAPSHOT_ROBOT_BYTES or used + size > SNAPSHOT_LINE_BYTES:
            log.warning(
                "Snapshot: leaving out robot %.100r (%d bytes; the snapshot line is full)", robot.get("key"), size
            )
            continue
        fitted.append(robot)
        used += size
    return fitted


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RecorderError(Exception):
    pass


class SessionRecorder:
    def __init__(
        self,
        directory: Path,
        max_bytes: int = DEFAULT_MAX_BYTES,
        on_stopped: Callable[[dict, str], None] | None = None,
    ):
        """`on_stopped(status, reason)` is called when recording stops by itself (size limit or write
        error), from the thread that recorded the last message."""
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self._on_stopped = on_stopped
        self._lock = threading.Lock()
        self._file = None
        self._current: dict | None = None
        self._started_monotonic = 0.0
        self._bytes = 0

    # --- Recording -------------------------------------------------------------

    def start(self, name: str | None, robots: list[dict]) -> dict:
        with self._lock:
            if self._current is not None:
                raise RecorderError(f"Already recording {self._current['sessionId']}")

            self.directory.mkdir(parents=True, exist_ok=True)
            session_id, self._file = self._create(datetime.now(UTC).strftime("%Y%m%d-%H%M%S"), name)
            self._bytes = 0
            self._started_monotonic = time.monotonic()
            self._current = {
                "sessionId": session_id,
                "name": name,
                "startedAt": _now(),
                "messageCount": 0,
            }
            self._write({"type": "session", "formatVersion": FORMAT_VERSION, **self._session_fields()})
            self._write({"type": "snapshot", "robots": fit_snapshot(robots)})
            return self._status()

    def _create(self, stamp: str, name: str | None):
        """Create the session file: timestamp (to the second) plus name; a suffix keeps two starts in the
        same second apart. Opened exclusively, so a file that appears under the same id meanwhile (an
        upload) is never truncated."""
        for attempt in range(1, 101):
            candidate = make_session_id(stamp, name, attempt)
            try:
                return candidate, (self.directory / f"{candidate}.jsonl").open("x", encoding="utf-8")
            except FileExistsError:
                continue
        raise RecorderError(f"Too many sessions named {make_session_id(stamp, name)}")

    def stop(self) -> dict:
        with self._lock:
            if self._current is None:
                raise RecorderError("Not recording")
            return self._finish("stopped")

    def _finish(self, reason: str) -> dict:
        """Write the end record (if the file still accepts writes) and close. Caller holds the lock."""
        status = self._status()
        try:
            self._write(
                {"type": "end", "endedAt": _now(), "messageCount": self._current["messageCount"], "reason": reason}
            )
        except OSError as error:
            log.error("Could not write end record of %s: %s", self._current["sessionId"], error)
        try:
            self._file.close()
        except OSError:
            pass
        self._file = None
        self._current = None
        return {**status, "recording": False}

    def record(self, message: dict) -> None:
        """Hub listener: append one MQTT message (called from the MQTT thread)."""
        with self._lock:
            if self._current is None:
                return
            line = {
                "type": "message",
                "t": round(time.monotonic() - self._started_monotonic, 3),
                "receivedAt": message["receivedAt"],
                "topic": message["topic"],
                "retained": message["retained"],
            }
            if message["validJson"]:
                line["payload"] = message["payload"]
            else:
                line["payloadRaw"] = message["payload"]
            if message.get("rejected"):
                line["rejected"] = message["rejected"]
            if message.get("issues"):
                line["issues"] = message["issues"]
            encoded = json.dumps(line, separators=(",", ":"), allow_nan=False) + "\n"
            if self._bytes + len(encoded.encode()) > self.max_bytes:
                reason = "sizeLimit"
                log.warning("Recording %s reached %d bytes; stopping", self._current["sessionId"], self.max_bytes)
            else:
                try:
                    self._write_encoded(encoded)
                    self._current["messageCount"] += 1
                    return
                except OSError as error:
                    reason = f"writeError: {error}"
                    log.error("Recording %s failed (%s); stopping", self._current["sessionId"], error)
            status = self._finish(reason)
        if self._on_stopped:
            self._on_stopped(status, reason)

    def status(self) -> dict | None:
        with self._lock:
            return self._status()

    def _status(self) -> dict | None:
        if self._current is None:
            return None
        return {
            **self._current,
            "recording": True,
            "duration": round(time.monotonic() - self._started_monotonic, 1),
            "sizeBytes": self._bytes,
            "maxBytes": self.max_bytes,
        }

    def _session_fields(self) -> dict:
        return {key: self._current[key] for key in ("sessionId", "name", "startedAt")}

    def _write(self, record: dict) -> None:
        self._write_encoded(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")

    def _write_encoded(self, line: str) -> None:
        self._file.write(line)
        self._file.flush()
        self._bytes += len(line.encode())

    # --- Stored sessions -------------------------------------------------------

    def path_for(self, session_id: str) -> Path | None:
        if not SESSION_ID.fullmatch(session_id):
            return None
        path = self.directory / f"{session_id}.jsonl"
        return path if path.is_file() else None

    def list_sessions(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        current = self.status()
        sessions = []
        for path in sorted(self.directory.glob("*.jsonl"), reverse=True):
            if not SESSION_ID.fullmatch(path.stem):
                continue
            try:
                if current and current["sessionId"] == path.stem:
                    sessions.append({**current, "sizeBytes": path.stat().st_size})
                else:
                    sessions.append(summarize(path))
            except FileNotFoundError:
                pass  # deleted since the directory was read
        return sessions


def _text(value) -> str | None:
    """A header/end field shown in the UI: a short string, or None (a file may hold anything)."""
    return value if isinstance(value, str) and len(value) <= MAX_FIELD_CHARS else None


def summarize(path: Path) -> dict:
    """Summary from the header (first line) and end record (last line). Only a file without an end
    record (cut off by a crash) is scanned to count its messages. Fields are sanitised: the file may
    be an upload or hand-edited, and the UI must get strings and numbers."""
    summary = {
        "sessionId": path.stem,
        "name": None,
        "startedAt": None,
        "endedAt": None,
        "messageCount": 0,
        "recording": False,
        "complete": False,
        "reason": None,
        "sizeBytes": path.stat().st_size,
    }
    with path.open("rb") as file:
        header = _parse(file.readline(MESSAGE_LINE_BYTES))
        if header and header.get("type") == "session":
            summary["name"] = _text(header.get("name"))
            summary["startedAt"] = _text(header.get("startedAt"))

        file.seek(max(0, summary["sizeBytes"] - TAIL_BYTES))
        tail = [line for line in file.read().splitlines() if line.strip()]
        end = _parse(tail[-1]) if tail else None
        if end and end.get("type") == "end":
            count = end.get("messageCount")
            summary.update(
                endedAt=_text(end.get("endedAt")),
                messageCount=count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else 0,
                complete=True,
                reason=_text(end.get("reason")),
            )
            return summary

    # No end record: the recording was cut off. Rare, so read every line rather than guess, which
    # also skips a half-written last line.
    summary["messageCount"] = sum(1 for _, record in iter_records(path) if (record or {}).get("type") == "message")
    return summary


def _parse(line: bytes) -> dict | None:
    return parse_line(line)[0]
