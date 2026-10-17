"""Session files on disk: retention and checking an uploaded file (D-41)."""

import json
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import vda5050
from app.jsonsafe import MAX_DEPTH, MAX_VALUES, REJECTED_RULES, loads, shape_rule
from app.live import MAX_ROBOTS
from app.recorder import FORMAT_VERSION, SESSION_ID, make_session_id
from app.session_records import (
    MAX_T,
    MESSAGE_LINE_BYTES,
    SNAPSHOT_ROBOT_BYTES,
    RecordError,
    parse_line,
    scan_records,
)

log = logging.getLogger("actunode.retention")

RECORD_TYPES = {"session", "snapshot", "message", "end"}
# A recording stopped at the size limit still gets its end record written, past the limit.
END_RECORD_RESERVE = 4 * 1024
# What an upload in progress leaves behind if the process dies (see tempfile.mkstemp in sessions.py).
UPLOAD_TEMP = re.compile(r"^\.upload-[A-Za-z0-9_]+\.tmp(\.id)?$")


class UploadError(Exception):
    """The uploaded file is not a valid session; the message names the first bad line."""


def _started(path: Path) -> datetime:
    """When the session started, from its id (UTC); the file's mtime if the id holds no valid date."""
    try:
        return datetime.strptime(path.stem[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)  # may raise FileNotFoundError: callers skip


def session_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [p for p in directory.glob("*.jsonl") if SESSION_ID.fullmatch(p.stem) and p.is_file()]


def _stats(directory: Path) -> dict[Path, os.stat_result]:
    """Size and times of each session file; one deleted meanwhile (another request, retention) is left out."""
    stats = {}
    for path in session_files(directory):
        try:
            stats[path] = path.stat()
        except FileNotFoundError:
            pass
    return stats


def enforce_retention(
    directory: Path, keep_days: int, max_total_mb: int, protected: set[str], now: datetime | None = None
) -> list[str]:
    """Delete sessions older than `keep_days`, then the oldest until the total is within `max_total_mb`
    (0 disables a rule). Sessions in `protected` stay. Returns the ids deleted."""
    now = now or datetime.now(UTC)
    stats = _stats(directory)
    # Ids only have whole seconds: the file's mtime breaks ties, so "oldest first" is well defined.
    files = sorted(((_started(p), p) for p in stats), key=lambda item: (item[0], stats[item[1]].st_mtime, item[1].name))
    sizes = {p: st.st_size for p, st in stats.items()}
    total = sum(sizes.values())
    deleted = []

    def delete(path: Path, why: str) -> None:
        nonlocal total
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            log.warning("Retention could not delete %s: %s", path.name, error)
            return
        total -= sizes[path]
        deleted.append(path.stem)
        log.info("Retention deleted session %s (%s)", path.stem, why)

    candidates = [(started, p) for started, p in files if p.stem not in protected]
    if keep_days:
        limit = now - timedelta(days=keep_days)
        for started, path in list(candidates):
            if started < limit:
                delete(path, f"older than {keep_days} days")
                candidates.remove((started, path))
    if max_total_mb:
        for _, path in candidates:
            if total <= max_total_mb * 1024 * 1024:
                break
            delete(path, f"sessions exceed {max_total_mb} MB")
    return deleted


def storage_used(directory: Path) -> tuple[int, int]:
    """(bytes used, number of sessions)."""
    stats = _stats(directory)
    return sum(st.st_size for st in stats.values()), len(stats)


def remove_upload_temps(directory: Path) -> None:
    """At startup: delete what an upload that never finished left behind (only files named like our temp files)."""
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if UPLOAD_TEMP.match(path.name):
            path.unlink(missing_ok=True)
            log.info("Removed leftover upload file %s", path.name)


# --- Uploads -------------------------------------------------------------------------


def _bad(number: int, reason: str) -> UploadError:
    return UploadError(f"Line {number}: {reason}")


def _optional_text(number: int, record: dict, field: str) -> None:
    if record.get(field) is not None and not isinstance(record[field], str):
        raise _bad(number, f"{field} must be text")


def check_upload(path: Path) -> dict:
    """Check a file line by line. Returns {header, ended, messages, lastReceivedAt, torn}: `torn` is the byte
    offset of an unparseable last line of a file with no end record (a crash cut it), to drop when storing.
    Raises UploadError naming the first bad line."""
    header = None
    ended = False
    messages = 0
    last_received = None
    torn = None
    try:
        for number, start, record in scan_records(path, strict=True):
            if ended:
                raise _bad(number, "nothing may follow the end record (it must be the last line)")
            if record is None:  # strict mode lets only the last line through like this
                if header is None:
                    raise _bad(number, "the first line must be a session header")
                torn = start
                break
            kind = record.get("type")
            if header is None:
                if kind != "session":
                    raise _bad(number, "the first line must be a session header")
                if record.get("formatVersion") != FORMAT_VERSION:
                    raise _bad(number, f"unsupported formatVersion {record.get('formatVersion')!r} (need 1)")
                _optional_text(number, record, "name")
                _optional_text(number, record, "startedAt")
                header = record
                continue
            if kind not in RECORD_TYPES:
                raise _bad(number, f"unknown record type {kind!r}")
            if kind == "session":
                raise _bad(number, "a second session header")
            if kind == "snapshot":
                _check_snapshot(number, record)
            if kind == "message":
                _check_message(number, record)
                messages += 1
                if isinstance(record.get("receivedAt"), str):
                    last_received = record["receivedAt"]
            if kind == "end":
                _check_end(number, record)
            ended = kind == "end"
    except RecordError as error:
        if ended:
            raise _bad(error.line, "nothing may follow the end record (it must be the last line)") from None
        raise _bad(error.line, error.reason) from None
    if header is None:
        raise _bad(1, "empty file, no session header")
    return {"header": header, "ended": ended, "messages": messages, "lastReceivedAt": last_received, "torn": torn}


def _check_snapshot(number: int, record: dict) -> None:
    robots = record.get("robots")
    if not isinstance(robots, list):
        raise _bad(number, "snapshot without a robots list")
    if len(robots) > MAX_ROBOTS:
        raise _bad(number, f"snapshot with more than {MAX_ROBOTS} robots")
    for robot in robots:
        if not isinstance(robot, dict):
            raise _bad(number, "snapshot robots must be objects")
        if len(json.dumps(robot)) > SNAPSHOT_ROBOT_BYTES:  # ASCII-escaped: cannot fail on a lone surrogate
            raise _bad(number, f"a snapshot robot is larger than {SNAPSHOT_ROBOT_BYTES} bytes")


def _check_end(number: int, record: dict) -> None:
    _optional_text(number, record, "endedAt")
    _optional_text(number, record, "reason")
    count = record.get("messageCount", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise _bad(number, "messageCount must be a whole number")


def _check_message(number: int, record: dict) -> None:
    topic = record.get("topic")
    if not isinstance(topic, str):
        raise _bad(number, "message without a topic")
    if len(topic) > vda5050.MAX_TOPIC_CHARS or vda5050.UNSAFE_TOPIC_CHARS.search(topic):
        raise _bad(number, f"topic longer than {vda5050.MAX_TOPIC_CHARS} characters or with control characters")
    t = record.get("t")
    if isinstance(t, bool) or not isinstance(t, int | float):
        raise _bad(number, "message without a numeric t")
    if not 0 <= t <= MAX_T:
        raise _bad(number, f"t must be between 0 and {MAX_T:g} seconds")
    rejected = record.get("rejected")
    if "rejected" in record and not (isinstance(rejected, str) and rejected in REJECTED_RULES):
        raise _bad(number, f"unknown rejected rule {record['rejected']!r}")
    if "payload" in record:
        rule = shape_rule(record["payload"])
        if rule == "too-deep":
            raise _bad(number, f"payload nested deeper than {MAX_DEPTH} levels")
        if rule:
            raise _bad(number, f"payload with more than {MAX_VALUES} values")
    elif not isinstance(record.get("payloadRaw"), str):
        raise _bad(number, "message with neither payload nor payloadRaw")


def new_session_id(directory: Path, name: str, clock: Callable[[], datetime], first: int = 1) -> tuple[str, int]:
    """The first id (timestamp, name, numeric suffix from the `first`-th try) with no file yet, and the try
    number it was found at."""
    stamp = clock().strftime("%Y%m%d-%H%M%S")
    n = first
    while (directory / f"{make_session_id(stamp, name, n)}.jsonl").exists():
        n += 1
    return make_session_id(stamp, name, n), n


class UploadWriter:
    """Receives the body of an upload into a temp file. The first line (the header) is held back until it is
    complete, then written with the server-chosen session id, so the file exists once on disk, not twice."""

    def __init__(self, file, directory: Path, choose_name: Callable[[dict | None], str], clock: Callable[[], datetime]):
        self._file, self._directory, self._choose_name, self._clock = file, directory, choose_name, clock
        self._held: bytearray | None = bytearray()
        self.session_id: str | None = None
        self.name = "upload"
        self.attempt = 1

    def feed(self, chunk: bytes) -> None:
        if self._held is None:
            self._file.write(chunk)
            return
        self._held += chunk
        if b"\n" in self._held or len(self._held) > MESSAGE_LINE_BYTES:
            self._release_first_line(complete=False)

    def close(self) -> None:
        try:
            if self._held is not None:
                self._release_first_line(complete=True)
        finally:
            self._file.close()

    def _release_first_line(self, complete: bool) -> None:
        """`complete`: the upload ended, so a first line without a newline is the whole file (D11)."""
        data, self._held = bytes(self._held), None
        line, newline, rest = data.partition(b"\n")
        header = parse_line(line)[0] if newline or complete else None
        if header is not None and header.get("type") == "session":
            self.name = self._choose_name(header)
            self.session_id, self.attempt = new_session_id(self._directory, self.name, self._clock)
            line = json.dumps({**header, "sessionId": self.session_id}, separators=(",", ":")).encode()
        self._file.write(line + newline + rest)


def finish_upload(
    temp: Path, directory: Path, writer: UploadWriter, checked: dict, clock: Callable[[], datetime]
) -> Path:
    """Make the checked temp file a clean, complete session and move it into place without overwriting an
    existing session: a torn last line is cut off, and a file without an end record gets one (so listing
    reads only its first and last line). Returns the final path."""
    with temp.open("rb+") as file:
        if checked["torn"] is not None:
            file.truncate(checked["torn"])
        if not checked["ended"]:
            end = {
                "type": "end",
                "endedAt": checked["lastReceivedAt"]
                or clock().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "messageCount": checked["messages"],
                "reason": "uploaded",
            }
            file.seek(0, os.SEEK_END)
            if file.tell():
                file.seek(-1, os.SEEK_END)
                if file.read(1) != b"\n":
                    file.write(b"\n")
            file.write(json.dumps(end, separators=(",", ":")).encode() + b"\n")
    final = directory / f"{writer.session_id}.jsonl"
    try:
        os.link(temp, final)  # fails rather than replacing a session that appeared meanwhile
        return final
    except FileExistsError:
        pass
    # Rare: the id was taken since it was chosen. Pick the next one; this copy rewrites the header.
    rewritten = temp.with_name(temp.name + ".id")
    n = writer.attempt
    try:
        while True:
            session_id, n = new_session_id(directory, writer.name, clock, n + 1)
            _rewrite_header(temp, rewritten, session_id)
            try:
                os.link(rewritten, directory / f"{session_id}.jsonl")
            except FileExistsError:
                continue
            return directory / f"{session_id}.jsonl"
    finally:
        rewritten.unlink(missing_ok=True)


def _rewrite_header(source: Path, target: Path, session_id: str) -> None:
    with source.open("rb") as src, target.open("wb") as dst:
        header = loads(src.readline())
        dst.write(json.dumps({**header, "sessionId": session_id}, separators=(",", ":")).encode() + b"\n")
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
