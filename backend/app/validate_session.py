"""Check a saved session file with the validator the live feed uses (D-40).

    python -m app.validate_session <file.jsonl>      (from backend/)

Exit code: 0 no error-severity issue, 1 at least one, 2 the file is not a readable ActuNode session.
"""

import json
import logging
import sys
from pathlib import Path

from app.jsonsafe import MAX_PAYLOAD_BYTES, REJECTED_RULES, parse_payload, shape_rule
from app.session_records import RecordError, iter_records
from app.validator import MAX_ISSUE_TEXT, RULES, Validator, issue

MAX_ISSUES = 100

log = logging.getLogger("actunode.validate")


class SessionFormatError(Exception):
    pass


def _check(validator: Validator, record: dict) -> list[dict]:
    """The issues the live hub would have found. Not reproduced here: proximity warnings, and header-id
    order against messages from before the recording started (the validator starts with no history).

    A payload the live parse rules rejected is stored as display text only (decoded with replacement
    characters, or a 1 KiB preview), which re-parses differently; the record names the rule instead
    (`rejected`). Older files lack it: their `payloadRaw` goes through the same parse rules."""
    topic = record["topic"]
    rejected = record.get("rejected")
    rejected = rejected if isinstance(rejected, str) and rejected in REJECTED_RULES else None
    if rejected:
        body = None
    elif "payloadRaw" in record:
        raw = record["payloadRaw"]
        body, rejected = parse_payload(raw.encode("utf-8", errors="replace") if isinstance(raw, str) else b"")
    else:
        body = record.get("payload")
        # surrogatepass: a lone surrogate (JSON allows "\ud800") must not make the measuring itself fail (D8)
        size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="surrogatepass"))
        if size > MAX_PAYLOAD_BYTES:
            rejected = "payload-too-large"  # the same size rule the live feed applies (D-31)
        else:
            rejected = shape_rule(body)
    if rejected:
        return [issue("error", rejected, RULES[rejected])]
    try:
        return validator.check(topic, body, True, bool(record.get("retained")))
    except Exception as error:
        log.exception("Validator failed on %s", topic)
        return [issue("error", "validator-error", f"{RULES['validator-error']}: {type(error).__name__}: {error}")]


def validate_session(path: Path, *, strict: bool = False) -> dict:
    """Check every message of a stored session. A line that is not usable (half-written, over-long, not UTF-8,
    NaN, too deeply nested) is skipped; `strict` (the command line) refuses the file at the first one instead,
    except a torn last line."""
    validator = Validator()
    checked = with_issues = 0
    by_rule: dict[str, dict] = {}
    issues: list[dict] = []
    truncated = False
    header = None
    try:
        for number, record in iter_records(path, strict=strict, parse_snapshot=False):  # line 2 is not needed
            if header is None:
                if record is None or record.get("type") != "session":
                    raise SessionFormatError("Not an ActuNode session (the first line must be a session header)")
                if record.get("formatVersion") != 1:
                    raise SessionFormatError(f"Unsupported session format version: {record.get('formatVersion')}")
                header = record
                continue
            if record is None or record.get("type") != "message" or not isinstance(record.get("topic"), str):
                continue
            checked += 1
            found = _check(validator, record)
            if not found:
                continue
            with_issues += 1
            for item in found:
                stats = by_rule.setdefault(
                    item["rule"],
                    {
                        "rule": item["rule"],
                        "description": RULES.get(item["rule"], ""),
                        "severity": item["severity"],
                        "count": 0,
                    },
                )
                stats["count"] += 1
                if len(issues) < MAX_ISSUES:
                    issues.append(
                        {
                            "line": number,
                            "t": record.get("t"),
                            "topic": record["topic"][:MAX_ISSUE_TEXT],
                            "rule": item["rule"],
                            "severity": item["severity"],
                            "message": item["message"],
                        }
                    )
                else:
                    truncated = True
    except RecordError as error:
        raise SessionFormatError(str(error)) from None
    if header is None:
        raise SessionFormatError("Not an ActuNode session (the file is empty)")
    return {
        "sessionId": header.get("sessionId") or Path(path).stem,
        "checked": checked,
        "withIssues": with_issues,
        "byRule": sorted(by_rule.values(), key=lambda rule: -rule["count"]),
        "issues": issues,
        "truncated": truncated,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m app.validate_session <file.jsonl>", file=sys.stderr)
        return 2
    try:
        result = validate_session(Path(args[0]), strict=True)
    except (OSError, UnicodeError, SessionFormatError) as error:
        print(f"{args[0]}: {error}", file=sys.stderr)
        return 2
    print(f"{result['sessionId']}: {result['checked']} messages checked, {result['withIssues']} with issues")
    for rule in result["byRule"]:
        print(f"  {rule['count']:>6}  {rule['severity']:<7} {rule['rule']}: {rule['description']}")
    for item in result["issues"][:20]:
        print(f"  line {item['line']}: [{item['severity']}] {item['rule']} on {item['topic']}: {item['message']}")
    if len(result["issues"]) > 20 or result["truncated"]:
        print("  ... more issues not listed")
    return 1 if any(rule["severity"] == "error" for rule in result["byRule"]) else 0


if __name__ == "__main__":
    sys.exit(main())
