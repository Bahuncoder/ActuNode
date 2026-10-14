"""actunode import: turn a `mosquitto_sub -F '%U %t %p'` capture into a session file (D-49).

Offline and read-only. The records mirror backend/app/recorder.py and the payload rules mirror
backend/app/jsonsafe.py, so offline validation of an imported file gives the same answers as for a
recording. The CLI is a separate package, hence the copies; test_import.py pins them.
"""

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

FORMAT_VERSION = 1
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_DEPTH = 32
PREVIEW_BYTES = 1024
MAX_TOPIC_BYTES = 65535  # the MQTT limit
MAX_LINE_BYTES = 1024 * 1024  # a longer capture line is skipped, never held in memory
MAX_SESSION_BYTES = 200 * 1024 * 1024  # the backend's default upload/recording limit
MAX_ROBOTS_LISTED = 1000
FIRST_BAD_LINES = 5
_TIME = re.compile(rb"(\d+(\.\d*)?|\.\d+)")
_ROBOT_TOPIC = re.compile(r"uagv/v\d+/([^/]+)/([^/]+)/[^/]+")


class ImportError_(Exception):
    """The capture cannot be turned into a session (reported, exit code 2)."""


class _NonFinite(ValueError):
    pass


def _reject_constant(name: str):
    raise _NonFinite(name)


def _too_deep(body) -> bool:
    level = [body] if isinstance(body, dict | list) else []
    depth = 1
    while level:
        if depth > MAX_DEPTH:
            return True
        level = [
            c
            for item in level
            for c in (item.values() if isinstance(item, dict) else item)
            if isinstance(c, dict | list)
        ]
        depth += 1
    return False


def parse_payload(payload: bytes) -> tuple[object, str | None]:
    """(body, None) for usable JSON, else (display text, name of the rule that rejects it)."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        text = payload[:PREVIEW_BYTES].decode("utf-8", errors="replace")
        return f"{text}… ({len(payload)} bytes, truncated for display)", "payload-too-large"
    try:
        body = json.loads(payload, parse_constant=_reject_constant)
    except RecursionError:
        return payload.decode("utf-8", errors="replace"), "too-deep"
    except _NonFinite:
        return payload.decode("utf-8", errors="replace"), "non-finite-number"
    except ValueError:
        return payload.decode("utf-8", errors="replace"), "invalid-json"
    if _too_deep(body):
        return payload.decode("utf-8", errors="replace"), "too-deep"
    return body, None


def clean_name(name: str | None) -> str | None:
    """As the backend cleans recording names: letters, digits, - and _, at most 40."""
    if not name:
        return None
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")[:40] or None


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_line(raw: bytes) -> tuple[float, str, bytes, str]:
    """(unix time, topic, payload bytes, payload text) of one capture line; ValueError says what is wrong."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not valid UTF-8") from None
    parts = text.split(" ", 2)
    if len(parts) < 3 or not parts[2]:
        raise ValueError("expected '<unix time> <topic> <payload>'")
    stamp, topic, payload = parts
    if not _TIME.fullmatch(stamp.encode()):
        raise ValueError("bad unix time")
    when = float(stamp)
    if not math.isfinite(when):
        raise ValueError("bad unix time")
    try:
        datetime.fromtimestamp(when, UTC)
    except (OverflowError, OSError, ValueError):
        raise ValueError("unix time out of range") from None
    if not topic or "+" in topic or "#" in topic or "\0" in topic:
        raise ValueError("bad topic")
    if len(topic.encode()) > MAX_TOPIC_BYTES:
        raise ValueError("topic too long")
    return when, topic, payload.encode(), payload


def convert(source, output: Path, name: str | None = None, strict: bool = False, force: bool = False) -> dict:
    """Stream `source` (binary file) to `output`; returns the figures for the summary. Raises ImportError_."""
    name = clean_name(name)
    if output.exists() and not force:
        raise ImportError_(f"{output} already exists (use --force to overwrite)")
    stats = {
        "messages": 0,
        "skipped": 0,
        "badLines": [],
        "backwards": 0,
        "bytes": 0,
        "firstAt": None,
        "lastAt": None,
        "seconds": 0.0,
        "robots": set(),
        "moreRobots": False,
        "sessionId": None,
    }
    out = None
    first = last_t = 0.0
    number = 0
    try:
        while True:
            raw = source.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            number += 1
            too_long = len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n")
            while too_long:  # drop the rest of the line in pieces
                rest = source.readline(MAX_LINE_BYTES)
                if not rest or rest.endswith(b"\n"):
                    break
            if too_long:
                reason = "line too long"
            else:
                raw = raw.removesuffix(b"\n").removesuffix(b"\r")
                if not raw.strip():
                    continue
                try:
                    when, topic, payload, text = parse_line(raw)
                    reason = None
                except ValueError as error:
                    reason = str(error)
            if reason:
                if strict:
                    raise ImportError_(f"line {number}: {reason}")
                stats["skipped"] += 1
                if len(stats["badLines"]) < FIRST_BAD_LINES:
                    stats["badLines"].append(number)
                continue

            moment = datetime.fromtimestamp(when, UTC)
            if out is None:
                started = _iso(moment)
                stamp = moment.strftime("%Y%m%d-%H%M%S")
                stats["sessionId"] = f"{stamp}_{name}" if name else stamp
                stats["firstAt"] = started
                first = when
                try:
                    out = output.open("w" if force else "x", encoding="utf-8")
                except OSError as error:
                    raise ImportError_(f"cannot write {output}: {error.strerror or error}") from None
                header = {"type": "session", "formatVersion": FORMAT_VERSION, "sessionId": stats["sessionId"]}
                _write(out, stats, {**header, "name": name, "startedAt": started})
                _write(out, stats, {"type": "snapshot", "robots": []})

            t = round(max(0.0, when - first), 3)
            if t < last_t:
                t = last_t
                stats["backwards"] += 1
            last_t = t
            body, rejected = parse_payload(payload)
            record = {"type": "message", "t": t, "receivedAt": _iso(moment), "topic": topic, "retained": False}
            record["payload" if rejected is None else "payloadRaw"] = body
            if rejected:
                record["rejected"] = rejected
            _write(out, stats, record)
            stats["messages"] += 1
            stats["lastAt"] = record["receivedAt"]
            stats["seconds"] = t
            match = _ROBOT_TOPIC.fullmatch(topic)
            if match:
                if len(stats["robots"]) < MAX_ROBOTS_LISTED:
                    stats["robots"].add(f"{match.group(1)}/{match.group(2)}")
                elif f"{match.group(1)}/{match.group(2)}" not in stats["robots"]:
                    stats["moreRobots"] = True

        if out is None:
            raise ImportError_("no usable message in the capture")
        _write(
            out,
            stats,
            {"type": "end", "endedAt": stats["lastAt"], "messageCount": stats["messages"], "reason": "stopped"},
        )
    except OSError as error:
        raise ImportError_(f"cannot read or write: {error.strerror or error}") from None
    except BaseException:
        if out is not None:
            out.close()
            out = None
            output.unlink(missing_ok=True)
        raise
    finally:
        if out is not None:
            out.close()
    return stats


def _write(out, stats: dict, record: dict) -> None:
    line = json.dumps(record, separators=(",", ":")) + "\n"
    out.write(line)
    stats["bytes"] += len(line)  # ASCII: json.dumps escapes everything else
