"""Parse rules for untrusted JSON, shared by the live hub, the session reader and the upload check (D-31)."""

import json
import math

# Untrusted MQTT payload limits. MAX_PAYLOAD_BYTES equals the broker's max_packet_size.
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_DEPTH = 32
PREVIEW_BYTES = 1024
# The rules parse_payload rejects a payload by (a recorded message names it in `rejected`).
REJECTED_RULES = {"invalid-json", "non-finite-number", "too-deep", "too-many-values", "payload-too-large"}
# Parsed JSON takes ~24x the memory of its text (every value is an object), so a byte limit alone does not bound
# memory: more values than this in one payload (containers and scalars together) are rejected (W4).
MAX_VALUES = 10_000
# Integers beyond this are refused as well: float() of a 400-digit int raises OverflowError (W1).
MAX_INT = 2**63


class NonFinite(ValueError):
    pass


def reject_constant(name: str):
    raise NonFinite(name)


def parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # 1e999
        raise NonFinite(text)
    return value


def parse_int(text: str) -> int:
    if len(text) > 25:  # do not even build a 4000-digit int
        raise NonFinite(text)
    value = int(text)
    if abs(value) > MAX_INT:
        raise NonFinite(text)
    return value


def loads(text: str | bytes):
    """json.loads with the rules for untrusted input: no NaN, Infinity, overflowing numbers."""
    return json.loads(text, parse_constant=reject_constant, parse_float=parse_float, parse_int=parse_int)


def count_values(body) -> int:
    """How many JSON values (containers and scalars) `body` holds; iterative, counting stops past MAX_VALUES."""
    level, values = [body] if isinstance(body, dict | list) else [], 1
    while level and values <= MAX_VALUES:
        children = [c for item in level for c in (item.values() if isinstance(item, dict) else item)]
        values += len(children)
        level = [c for c in children if isinstance(c, dict | list)]
    return values


def shape_rule(body) -> str | None:
    """ "too-deep" if `body` nests containers deeper than MAX_DEPTH, "too-many-values" if it holds more than
    MAX_VALUES values, else None. Iterative: recursion is what deep payloads attack."""
    level = [body] if isinstance(body, dict | list) else []
    depth, values = 1, 1
    while level:
        if depth > MAX_DEPTH:
            return "too-deep"
        children = [c for item in level for c in (item.values() if isinstance(item, dict) else item)]
        values += len(children)
        if values > MAX_VALUES:
            return "too-many-values"
        level = [c for c in children if isinstance(c, dict | list)]
        depth += 1
    return None


def preview(raw: bytes) -> str:
    return f"{raw[:PREVIEW_BYTES].decode('utf-8', errors='replace')}… ({len(raw)} bytes, truncated for display)"


def parse_payload(payload: bytes) -> tuple[object, str | None]:
    """(body, None) for a usable JSON payload, else (text kept for display, rule that rejected it)."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        return preview(payload), "payload-too-large"
    try:
        text = payload.decode("utf-8")  # strict, first: json.loads on bytes would also accept UTF-16/32 (W9)
        body = loads(text)  # a BOM makes it invalid JSON
    except RecursionError:
        return payload.decode("utf-8", errors="replace"), "too-deep"
    except NonFinite:
        return payload.decode("utf-8", errors="replace"), "non-finite-number"
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        return payload.decode("utf-8", errors="replace"), "invalid-json"
    if rule := shape_rule(body):
        return payload.decode("utf-8", errors="replace"), rule
    return body, None
