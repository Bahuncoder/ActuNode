"""Record MQTT traffic to JSONL session files.

File layout, one JSON object per line:

    {"type": "session",  "formatVersion": 1, "sessionId", "name", "startedAt"}
    {"type": "snapshot", "robots": [...]}            latest robot states at start
    {"type": "message",  "t", "receivedAt", "topic", "retained", "payload", "issues"?}   (many)
    {"type": "end",      "endedAt", "messageCount"}  missing if the backend crashed

`t` is seconds since recording started. `payload` is the parsed JSON; a message
that was not valid JSON is stored as the raw string in `payloadRaw` instead.
`issues` (validator findings) is present only when the message had any.
"""

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = 1
SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(_[A-Za-z0-9_-]{1,40})?$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RecorderError(Exception):
    pass


class SessionRecorder:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._file = None
        self._current: dict | None = None
        self._started_monotonic = 0.0

    # --- Recording -------------------------------------------------------------

    def start(self, name: str | None, robots: list[dict]) -> dict:
        with self._lock:
            if self._current is not None:
                raise RecorderError(f"Already recording {self._current['sessionId']}")

            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            session_id = f"{stamp}_{name}" if name else stamp
            path = self.directory / f"{session_id}.jsonl"
            if path.exists():
                raise RecorderError(f"Session {session_id} already exists")

            self._file = path.open("w", encoding="utf-8")
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
            self._write({"type": "end", "endedAt": _now(), "messageCount": self._current["messageCount"]})
            self._file.close()
            status = self._status()
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
            self._write(line)
            self._current["messageCount"] += 1

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
        }

    def _session_fields(self) -> dict:
        return {key: self._current[key] for key in ("sessionId", "name", "startedAt")}

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()

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
    """Read a session file's header and footer without loading every message."""
    summary = {
        "sessionId": path.stem,
        "name": None,
        "startedAt": None,
        "endedAt": None,
        "messageCount": 0,
        "recording": False,
        "complete": False,
        "sizeBytes": path.stat().st_size,
    }
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a crash can leave a half-written last line
            kind = record.get("type")
            if kind == "session":
                summary["name"] = record.get("name")
                summary["startedAt"] = record.get("startedAt")
            elif kind == "message":
                summary["messageCount"] += 1
            elif kind == "end":
                summary["endedAt"] = record.get("endedAt")
                summary["complete"] = True
    return summary
