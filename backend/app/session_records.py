"""One reader for session files (JSON Lines): bounded lines, strict UTF-8, no NaN, no deep nesting (D-31, D-41).

Used by the upload check (strict), validation, replay and listing, so they all agree on what a line is."""

import json
from collections.abc import Iterator
from pathlib import Path

from app.jsonsafe import MAX_DEPTH, MAX_PAYLOAD_BYTES, NonFinite, reject_constant
from app.live import MAX_ROBOTS, MAX_STORED_STATE_BYTES

# A message line is the payload plus the record's own fields. The payload text can grow when written:
# JSON escapes each invalid UTF-8 byte (U+FFFD) as 6 bytes, so 6 x the payload limit plus the other fields.
MESSAGE_LINE_BYTES = 6 * MAX_PAYLOAD_BYTES + 4 * 1024
# The snapshot (line 2) holds the latest state of every robot; non-ASCII text can triple when escaped.
SNAPSHOT_LINE_BYTES = 3 * MAX_ROBOTS * MAX_STORED_STATE_BYTES + 64 * 1024


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
        record = json.loads(text, parse_constant=reject_constant)
    except NonFinite:
        return None, "NaN or Infinity is not valid JSON"
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


def scan_records(path: Path, *, strict: bool = False) -> Iterator[tuple[int, int, dict | None]]:
    """(line number, byte offset of the line, record) for each line; record is None for a line that is not
    a usable JSON object (half-written, foreign, over-long, not UTF-8). Strict raises RecordError for such a
    line instead, except the last line of the file, which a crash can tear: that one is still yielded as None."""
    with Path(path).open("rb") as file:
        number = 0
        while True:
            number += 1
            start = file.tell()
            raw, reason = read_line(file, number)
            if not raw and reason is None:
                return
            record = None
            if reason is None:
                record, reason = parse_line(raw)
            if record is None and strict and (reason not in TORN or file.peek(1)):
                raise RecordError(number, reason)
            yield number, start, record


def iter_records(path: Path, *, strict: bool = False) -> Iterator[tuple[int, dict | None]]:
    """(line number, record) for each line; see scan_records."""
    for number, _, record in scan_records(path, strict=strict):
        yield number, record
