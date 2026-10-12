import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.validate_session import SessionFormatError, main, validate_session

FIXTURES = Path(__file__).parent / "fixtures"
BACKEND = Path(__file__).resolve().parents[1]


def fixture(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return data["topic"], data["payload"]


def message(t, topic, payload=None, raw=None):
    record = {"type": "message", "t": t, "receivedAt": "x", "topic": topic, "retained": False}
    record["payloadRaw" if raw is not None else "payload"] = raw if raw is not None else payload
    return record


def write(path, records, header=True, end=True):
    lines = []
    if header:
        lines.append({"type": "session", "formatVersion": 1, "sessionId": path.stem, "name": None, "startedAt": "x"})
        lines.append({"type": "snapshot", "robots": []})
    lines += records
    if end:
        lines.append({"type": "end", "endedAt": "x", "messageCount": len(records), "reason": "stopped"})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def clean_records():
    return [message(0.1, *fixture("connection")), message(0.2, *fixture("order"))]


def test_clean_session_has_no_issues(tmp_path):
    path = write(tmp_path / "20261009-120000_clean.jsonl", clean_records())

    result = validate_session(path)

    assert result == {
        "sessionId": "20261009-120000_clean",
        "checked": 2,
        "withIssues": 0,
        "byRule": [],
        "issues": [],
        "truncated": False,
    }


def test_planted_problems_are_counted_per_rule_with_line_numbers(tmp_path):
    topic, state = fixture("state_moving")
    no_battery = copy.deepcopy(state)
    del no_battery["batteryState"]["batteryCharge"]
    c_topic, wrong_serial = fixture("connection")
    wrong_serial["serialNumber"] = "robot_99"
    wrong_serial["headerId"] += 10
    records = [
        *clean_records(),  # lines 3, 4
        message(0.3, topic, no_battery),  # line 5
        message(0.4, topic, raw="{broken"),  # line 6
        message(0.5, c_topic, wrong_serial),  # line 7
        message(0.6, topic, raw="{broken"),  # line 8
    ]
    path = write(tmp_path / "20261009-120000_bad.jsonl", records)

    result = validate_session(path)

    assert result["checked"] == 6
    assert result["withIssues"] == 4
    assert [(r["rule"], r["count"]) for r in result["byRule"]] == [
        ("invalid-json", 2),
        ("schema", 1),
        ("topic-mismatch", 1),
    ]
    assert result["byRule"][0]["severity"] == "error"
    assert result["byRule"][0]["description"]
    assert [(i["line"], i["rule"]) for i in result["issues"]] == [
        (5, "schema"),
        (6, "invalid-json"),
        (7, "topic-mismatch"),
        (8, "invalid-json"),
    ]
    first = result["issues"][1]
    assert first["t"] == 0.4 and first["topic"] == topic and first["severity"] == "error" and first["message"]
    assert result["truncated"] is False


def test_payload_raw_that_is_really_json_is_checked_as_a_payload(tmp_path):
    topic, payload = fixture("connection")
    path = write(tmp_path / "20261009-120000_raw.jsonl", [message(0, topic, raw=json.dumps(payload))])

    assert validate_session(path)["withIssues"] == 0


def test_more_than_100_issues_are_truncated_but_all_counted(tmp_path):
    topic = "uagv/v2/ActuNode/robot_01/state"
    path = write(tmp_path / "20261009-120000_many.jsonl", [message(i, topic, raw="{x") for i in range(130)])

    result = validate_session(path)

    assert result["withIssues"] == 130
    assert result["byRule"][0]["count"] == 130
    assert len(result["issues"]) == 100
    assert result["truncated"] is True


@pytest.mark.parametrize("header", [False, True])
def test_not_a_session_file_is_a_format_error(tmp_path, header):
    path = tmp_path / "20261009-120000_x.jsonl"
    if header:
        path.write_text('{"type":"session","formatVersion":2}\n')
    else:
        write(path, clean_records(), header=False)

    with pytest.raises(SessionFormatError):
        validate_session(path)


def test_cli_exit_codes(tmp_path, capsys):
    clean = write(tmp_path / "20261009-120000_clean.jsonl", clean_records())
    bad = write(tmp_path / "20261009-120001_bad.jsonl", [message(0, "uagv/v2/ActuNode/robot_01/state", raw="{x")])
    invalid = tmp_path / "20261009-120002_junk.jsonl"
    invalid.write_text("not a session\n")

    assert main([str(clean)]) == 0
    assert main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert "invalid-json" in out and "line 3" in out
    assert main([str(invalid)]) == 2
    assert main([str(tmp_path / "missing.jsonl")]) == 2


def test_cli_runs_as_a_module(tmp_path):
    clean = write(tmp_path / "20261009-120000_clean.jsonl", clean_records())

    done = subprocess.run(
        [sys.executable, "-m", "app.validate_session", str(clean)], cwd=BACKEND, capture_output=True, text=True
    )

    assert done.returncode == 0, done.stderr


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_validate_endpoint(client, tmp_path):
    write(tmp_path / "20261009-120000_api.jsonl", [message(0, "uagv/v2/ActuNode/robot_01/state", raw="{x")])

    response = client.post("/api/sessions/20261009-120000_api/validate")

    assert response.status_code == 200
    assert response.json()["sessionId"] == "20261009-120000_api"
    assert response.json()["byRule"][0]["rule"] == "invalid-json"


def test_validate_endpoint_unknown_bad_id_and_recording(client, tmp_path):
    assert client.post("/api/sessions/20261009-120000_none/validate").status_code == 404
    assert client.post("/api/sessions/..%2Fetc/validate").status_code == 404
    status = client.post("/api/recording/start", json={"name": "live"}).json()

    assert client.post(f"/api/sessions/{status['sessionId']}/validate").status_code == 409
    client.post("/api/recording/stop")
    assert client.post(f"/api/sessions/{status['sessionId']}/validate").status_code == 200


def test_validate_endpoint_reports_unusable_file_as_422(client, tmp_path):
    (tmp_path / "20261009-120000_junk.jsonl").write_text("nope\n")

    assert client.post("/api/sessions/20261009-120000_junk/validate").status_code == 422


# --- the command line must not crash on hostile files (S7) -------------------------------

HEADER_LINE = '{"type": "session", "formatVersion": 1}\n{"type": "snapshot", "robots": []}\n'


def run_cli(tmp_path, content: bytes, capsys):
    path = tmp_path / "x.jsonl"
    path.write_bytes(HEADER_LINE.encode() + content)
    code = main([str(path)])
    return code, capsys.readouterr()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b'{"type":"message","t":1,"topic":"a","payload":' + b"[" * 100000 + b"]" * 100000 + b"}\n", "deeper"),
        (b'{"type":"message","t":NaN,"topic":"a","payload":{}}\n', "NaN"),
        (b'{"type":"message","t":1,"topic":"a","payload":"' + b"a" * (2 * 1024 * 1024) + b'"}\n', "too long"),
        (b'{"type":"message","t":1,"topic":"t","payload":"\xff"}\n', "UTF-8"),
    ],
    ids=["deep", "nan", "too-long", "not-utf8"],
)
def test_cli_exits_2_with_a_message_for_hostile_lines(tmp_path, capsys, content, expected):
    code, out = run_cli(tmp_path, content + b'{"type":"end"}\n', capsys)

    assert code == 2
    assert "line 3" in out.err.lower() and expected.lower() in out.err.lower()


def test_cli_tolerates_a_torn_last_line(tmp_path, capsys):
    code, out = run_cli(tmp_path, b'{"type":"message","t":1,"topic":"a/b","payload":{}}\n{"type":"mess', capsys)

    assert code in (0, 1) and "1 messages checked" in out.out


def test_cli_applies_the_payload_size_limit(tmp_path, capsys):
    from app.jsonsafe import MAX_PAYLOAD_BYTES

    big = {"type": "message", "t": 1, "topic": "a/b", "payload": {"x": "a" * (MAX_PAYLOAD_BYTES + 10)}}
    code, out = run_cli(tmp_path, json.dumps(big).encode() + b"\n", capsys)

    assert code == 1 and "payload-too-large" in out.out
