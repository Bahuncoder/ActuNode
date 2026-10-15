"""One reader for session files (JSON Lines): bounded lines, strict UTF-8, no NaN, no deep nesting (D-31, D-41).

Used by the upload check (strict), validation, replay and listing, so they all agree on what a line is."""

import re
from collections.abc import Iterator
from pathlib import Path

from app.jsonsafe import MAX_DEPTH, MAX_PAYLOAD_BYTES, NonFinite, loads
from app.live import MAX_STORED_STATE_BYTES

# A message line is the payload plus the record's own fields. The payload text can grow when written:
# JSON escapes each invalid UTF-8 byte (U+FFFD) as 6 bytes, so 6 x the payload limit plus the other fields.
MESSAGE_LINE_BYTES = 6 * MAX_PAYLOAD_BYTES + 4 * 1024
# The snapshot (line 2) holds the latest state of every robot. Parsed, a line takes ~25x its size in memory, so
# the limit is what the recorder is allowed to write (it leaves robots out that do not fit, recorder.fit_snapshot),
# not the theoretical MAX_ROBOTS x 3 (escaping) x MAX_STORED_STATE_BYTES, which would be the whole 200 MB file (D2).
SNAPSHOT_LINE_BYTES = 8 * 1024 * 1024
# One snapshot robot, encoded: its stored state (non-ASCII text can triple when escaped) plus its identity fields.
SNAPSHOT_ROBOT_BYTES = 3 * MAX_STORED_STATE_BYTES + 4 * 1024
# Line 2 as the recorder writes it; validation does not need the robots and skips parsing it.
SNAPSHOT_PREFIX = re.compile(rb'\s*\{\s*"type"\s*:\s*"snapshot"')


# A recording runs for a year at most; anything else in a message's `t` is a broken or hostile file (a replay
# would sleep for ever on it).
MAX_T = 366 * 24 * 3600.0


# Why a last line can be a crash's torn write; anything else (NaN, nesting, size) is refused wherever it is.
TORN = {"not valid JSON", "not valid UTF-8"}


class RecordError(Exception):
    def __init__(self, line: int, reason: str):
        super().__init__(f"Line {line}: {reason}")
        self.line = line
        self.reason = reason


def line_limit(number: int) -> int:
    return SNAPSHOT_LINE_BYTES if number == 2 else MESSAGE_LINE_BYTES


def parse_line(raw: bytes) -> tuple[dict | None, str | None]:
    """(record, None), or (None, why the line is unusable). UTF-8 is decoded explicitly: json.loads on
    bytes would also accept UTF-16/32."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not valid UTF-8"
    try:
        record = loads(text)
    except NonFinite:
        return None, "NaN, Infinity or a number too large is not valid JSON"
    except RecursionError:
        return None, f"nested deeper than {MAX_DEPTH} levels"
    except ValueError:
        return None, "not valid JSON"
    return (record, None) if isinstance(record, dict) else (None, "not a JSON object")


def read_line(file, number: int) -> tuple[bytes, str | None]:
    """The next line (empty at the end of the file) and, if it was longer than the limit, the reason; the
    rest of such a line is read and dropped in pieces, never held."""
    limit = line_limit(number)
    raw = file.readline(limit + 1)
    if len(raw) <= limit or raw.endswith(b"\n"):
        return raw, None
    while not (rest := file.readline(1024 * 1024)).endswith(b"\n") and rest:
        pass
    return b"", f"line too long (more than {limit} bytes)"


def scan_records(
    path: Path, *, strict: bool = False, parse_snapshot: bool = True
) -> Iterator[tuple[int, int, dict | None]]:
    """(line number, byte offset of the line, record) for each line; record is None for a line that is not
    a usable JSON object (half-written, foreign, over-long, not UTF-8). Strict raises RecordError for such a
    line instead, except the last line of the file, which a crash can tear: that one is still yielded as None.
    With parse_snapshot=False, line 2 is not parsed when it is a snapshot: it is yielded as {"type": "snapshot"}."""
    with Path(path).open("rb") as file:
        number = 0
        while True:
            number += 1
            start = file.tell()
            raw, reason = read_line(file, number)
            if not raw and reason is None:
                return
            record = None
            if reason is None and number == 2 and not parse_snapshot and SNAPSHOT_PREFIX.match(raw):
                record = {"type": "snapshot"}
            elif reason is None:
                record, reason = parse_line(raw)
            if record is None and strict and (reason not in TORN or file.peek(1)):
                raise RecordError(number, reason)
            yield number, start, record


def iter_records(path: Path, *, strict: bool = False, parse_snapshot: bool = True) -> Iterator[tuple[int, dict | None]]:
    """(line number, record) for each line; see scan_records."""
    for number, _, record in scan_records(path, strict=strict, parse_snapshot=parse_snapshot):
        yield number, record
