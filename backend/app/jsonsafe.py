"""Parse rules for untrusted JSON, shared by the live hub, the session reader and the upload check (D-31)."""

import json

# Untrusted MQTT payload limits. MAX_PAYLOAD_BYTES equals the broker's max_packet_size.
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_DEPTH = 32
PREVIEW_BYTES = 1024
# The rules parse_payload rejects a payload by (a recorded message names it in `rejected`).
REJECTED_RULES = {"invalid-json", "non-finite-number", "too-deep", "payload-too-large"}


class NonFinite(ValueError):
    pass


def reject_constant(name: str):
    raise NonFinite(name)


def too_deep(body) -> bool:
    """True if `body` nests containers deeper than MAX_DEPTH. Iterative: recursion is what deep payloads attack."""
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


def preview(raw: bytes) -> str:
    return f"{raw[:PREVIEW_BYTES].decode('utf-8', errors='replace')}… ({len(raw)} bytes, truncated for display)"


def parse_payload(payload: bytes) -> tuple[object, str | None]:
    """(body, None) for a usable JSON payload, else (text kept for display, rule that rejected it)."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        return preview(payload), "payload-too-large"
    try:
        body = json.loads(payload, parse_constant=reject_constant)
    except RecursionError:
        return payload.decode("utf-8", errors="replace"), "too-deep"
    except NonFinite:
        return payload.decode("utf-8", errors="replace"), "non-finite-number"
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        return payload.decode("utf-8", errors="replace"), "invalid-json"
    if too_deep(body):
        return payload.decode("utf-8", errors="replace"), "too-deep"
    return body, None
