"""actunode import: a mosquitto_sub capture becomes a session file the backend accepts (D-49)."""

import io
import json

from actunode import cli

STATE = "uagv/v2/ActuNode/robot_01/state"
T0 = 1760450000


def run(tmp_path, capture, *extra, stdin=None):
    """(exit code, output text, session records or None)."""
    source = tmp_path / "capture.txt"
    if capture is not None and stdin is None:
        source.write_bytes(capture if isinstance(capture, bytes) else capture.encode())
    target = tmp_path / "site.jsonl"
    out = io.StringIO()
    argv = ["import", "-" if stdin is not None else str(source), "-o", str(target), *extra]
    code = cli.main(argv, out=out, stdin=io.BytesIO(stdin) if stdin is not None else None)
    records = (
        [json.loads(line) for line in target.read_text().splitlines()]
        if target.exists() and target.read_text().startswith("{")
        else None
    )
    return code, out.getvalue(), records


def test_a_good_capture_becomes_the_recorders_records(tmp_path):
    capture = (
        f'{T0}.123456789 {STATE} {{"orderId":"o1","x":1}}\n'
        f"{T0 + 1}.5 uagv/v2/ActuNode/robot_01/connection not json at all\n"
        f"{T0 + 2} uagv/v2/ActuNode/robot_02/state [1, 2]\r\n"
    )
    code, out, records = run(tmp_path, capture)
    assert code == 0
    assert records[0] == {
        "type": "session",
        "formatVersion": 1,
        "sessionId": "20251014-135320",
        "name": None,
        "startedAt": "2025-10-14T13:53:20.123Z",
    }
    assert records[1] == {"type": "snapshot", "robots": []}
    assert records[2] == {
        "type": "message",
        "t": 0.0,
        "receivedAt": "2025-10-14T13:53:20.123Z",
        "topic": STATE,
        "retained": False,
        "payload": {"orderId": "o1", "x": 1},
    }
    assert records[3] == {
        "type": "message",
        "t": 1.377,
        "receivedAt": "2025-10-14T13:53:21.500Z",
        "topic": "uagv/v2/ActuNode/robot_01/connection",
        "retained": False,
        "payloadRaw": "not json at all",
        "rejected": "invalid-json",
    }
    assert records[4]["payload"] == [1, 2] and records[4]["t"] == 1.877
    assert records[5] == {
        "type": "end",
        "endedAt": "2025-10-14T13:53:22.000Z",
        "messageCount": 3,
        "reason": "stopped",
    }
    assert "3 message(s) written" in out and "robots seen: 2 (ActuNode/robot_01, ActuNode/robot_02)" in out
    assert "POST /api/sessions/upload" in out


def test_payload_with_spaces_is_kept_whole(tmp_path):
    code, _, records = run(tmp_path, f'{T0} {STATE} {{"a": "x y  z", "b": [1, 2]}}\n')
    assert code == 0 and records[2]["payload"] == {"a": "x y  z", "b": [1, 2]}


def test_rejected_payloads_follow_the_live_parse_rules(tmp_path):
    nested = "[" * 40 + "]" * 40
    lines = f'{T0} t/a {{bad\n{T0} t/b {{"x": NaN}}\n{T0} t/c {nested}\n{T0} t/d {"x" * 300000}\n'
    _, _, records = run(tmp_path, lines)
    rules = [r["rejected"] for r in records[2:-1]]
    assert rules == ["invalid-json", "non-finite-number", "too-deep", "payload-too-large"]
    assert all("payload" not in r for r in records[2:-1])
    assert "truncated for display" in records[5]["payloadRaw"]


def test_unreadable_lines_are_skipped_and_counted(tmp_path):
    capture = (
        f"{T0} {STATE} {{}}\n".encode()
        + b"\n"
        + f"{T0} {STATE} caf".encode()
        + b"\xff\n"
        + f"nope {STATE} {{}}\n".encode()
        + f"{T0} uagv/+/state {{}}\n".encode()
        + f"{T0} uagv/#/state {{}}\n".encode()
        + f"{T0} {STATE}\n".encode()
        + f"-5 {STATE} {{}}\n".encode()
        + f"{T0} {STATE} {{}}\n".encode()
    )
    code, out, records = run(tmp_path, capture)
    assert code == 0 and records[-1]["messageCount"] == 2
    assert "skipped 6 line(s)" in out and "first: 3, 4, 5, 6, 7" in out


def test_strict_stops_at_the_first_bad_line_and_leaves_no_file(tmp_path):
    code, out, records = run(tmp_path, f"{T0} {STATE} {{}}\nbad line\n", "--strict")
    assert code == 2 and "line 2" in out and records is None


def test_no_usable_message_is_exit_2_without_a_file(tmp_path):
    code, out, records = run(tmp_path, "garbage\n\n")
    assert code == 2 and "no usable message" in out and records is None


def test_reads_standard_input(tmp_path):
    code, _, records = run(tmp_path, None, stdin=f"{T0} {STATE} {{}}\n".encode())
    assert code == 0 and records[-1]["messageCount"] == 1


def test_missing_capture_file_is_exit_2(tmp_path):
    out = io.StringIO()
    assert cli.main(["import", str(tmp_path / "none.txt"), "-o", str(tmp_path / "o.jsonl")], out=out) == 2
    assert "cannot read" in out.getvalue()


def test_refuses_to_overwrite_unless_forced(tmp_path):
    (tmp_path / "site.jsonl").write_text("keep me")
    code, out, _ = run(tmp_path, f"{T0} {STATE} {{}}\n")
    assert code == 2 and "already exists" in out
    assert (tmp_path / "site.jsonl").read_text() == "keep me"
    code, _, records = run(tmp_path, f"{T0} {STATE} {{}}\n", "--force")
    assert code == 0 and records[0]["type"] == "session"


def test_time_going_backwards_is_clamped_and_counted(tmp_path):
    code, out, records = run(tmp_path, f"{T0} t/a {{}}\n{T0 + 5} t/a {{}}\n{T0 + 2} t/a {{}}\n{T0 - 9} t/a {{}}\n")
    assert code == 0
    assert [r["t"] for r in records[2:-1]] == [0.0, 5.0, 5.0, 5.0]
    assert "2 timestamp(s) went backwards" in out


def test_name_is_cleaned_like_the_backend_does(tmp_path):
    _, _, records = run(tmp_path, f"{T0} t/a {{}}\n", "--name", " site A/line 3! " + "x" * 50)
    name = records[0]["name"]
    assert name.startswith("site-A-line-3-x") and len(name) == 40
    assert records[0]["sessionId"] == f"20251014-135320_{name}"


def test_a_large_capture_streams(tmp_path):
    capture = "".join(f'{T0 + i / 100} {STATE} {{"n":{i}}}\n' for i in range(20_000))
    code, _, records = run(tmp_path, capture)
    assert code == 0 and records[-1]["messageCount"] == 20_000


def test_hostile_text_in_the_summary_is_neutralised(tmp_path):
    out = io.StringIO()
    capture = tmp_path / "c.txt"
    capture.write_text(f"{T0} uagv/v2/\x1b[31mevil/\x07x/state {{}}\n")
    assert cli.main(["import", str(capture), "-o", str(tmp_path / "o.jsonl"), "--name", "\x1b[2J"], out=out) == 0
    assert "\x1b" not in out.getvalue() and "\x07" not in out.getvalue()
    assert "\\x1b[31mevil" in out.getvalue()
