"""Record MQTT traffic to JSONL session files.

File layout, one JSON object per line:

    {"type": "session",  "formatVersion": 1, "sessionId", "name", "startedAt"}
    {"type": "snapshot", "robots": [...]}            latest robot states at start
    {"type": "message",  "t", "receivedAt", "topic", "retained", "payload", "issues"?}   (many)
    {"type": "end",      "endedAt", "messageCount", "reason"}  missing if the backend crashed

`t` is seconds since recording started. `payload` is the parsed JSON; a message
that was not valid JSON is stored as the raw string in `payloadRaw` instead.
`issues` (validator findings) is present only when the message had any.
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

log = logging.getLogger("actunode.recorder")

FORMAT_VERSION = 1
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
# Read at most this much from the end of a file to find its end record.
TAIL_BYTES = 64 * 1024
SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(_[A-Za-z0-9_-]{1,40})?$")


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
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            session_id = f"{stamp}_{name}" if name else stamp
            path = self.directory / f"{session_id}.jsonl"
            if path.exists():
                raise RecorderError(f"Session {session_id} already exists")

            self._file = path.open("w", encoding="utf-8")
            self._bytes = 0
            self._started_monotonic = time.monotonic()
            self._current = {
                "sessionId": session_id,
                "name": name,
                "startedAt": _now(),
                "messageCount": 0,
            }
            self._write({"type": "session", "formatVersion": FORMAT_VERSION, **self._session_fields()})
            self._write({"type": "snapshot", "robots": robots})
            return self._status()

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
        return status

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
            if message.get("issues"):
                line["issues"] = message["issues"]
            encoded = json.dumps(line, separators=(",", ":")) + "\n"
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
        self._write_encoded(json.dumps(record, separators=(",", ":")) + "\n")

    def _write_encoded(self, line: str) -> None:
        self._file.write(line)
        self._file.flush()
        self._bytes += len(line.encode())

    # --- Stored sessions -------------------------------------------------------

    def path_for(self, session_id: str) -> Path | None:
        if not SESSION_ID.match(session_id):
            return None
        path = self.directory / f"{session_id}.jsonl"
        return path if path.is_file() else None

    def list_sessions(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        current = self.status()
        sessions = []
        for path in sorted(self.directory.glob("*.jsonl"), reverse=True):
            if not SESSION_ID.match(path.stem):
                continue
            if current and current["sessionId"] == path.stem:
                sessions.append({**current, "sizeBytes": path.stat().st_size})
            else:
                sessions.append(summarize(path))
        return sessions


def summarize(path: Path) -> dict:
    """Summary from the header (first line) and end record (last line). Only a file without an end
    record (cut off by a crash) is scanned to count its messages."""
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
        header = _parse(file.readline())
        if header and header.get("type") == "session":
            summary["name"] = header.get("name")
            summary["startedAt"] = header.get("startedAt")

        file.seek(max(0, summary["sizeBytes"] - TAIL_BYTES))
        tail = [line for line in file.read().splitlines() if line.strip()]
        end = _parse(tail[-1]) if tail else None
        if end and end.get("type") == "end":
            summary.update(
                endedAt=end.get("endedAt"),
                messageCount=end.get("messageCount", 0),
                complete=True,
                reason=end.get("reason"),
            )
            return summary

        # No end record: the recording was cut off. Rare, so parse every line rather than guess,
        # which also skips a half-written last line.
        file.seek(0)
        summary["messageCount"] = sum(1 for line in file if (_parse(line) or {}).get("type") == "message")
    return summary


def _parse(line: bytes) -> dict | None:
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None  # a crash can leave a half-written line
    return record if isinstance(record, dict) else None
