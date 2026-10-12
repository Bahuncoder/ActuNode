"""Files the recorder really writes must be accepted by the upload check, and validate offline like live (D-41)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.jsonsafe import MAX_PAYLOAD_BYTES
from app.live import LiveHub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.recorder import SessionRecorder
from app.validate_session import validate_session

FIXTURES = Path(__file__).parent / "fixtures"
STATE = json.loads((FIXTURES / "state_moving.json").read_text())
TOPIC = "uagv/v2/ActuNode/robot_01/state"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path / "store")
    with TestClient(app) as test_client:
        yield test_client


def record(tmp_path, publish, prepare=lambda hub: None, max_bytes=200 * 1024 * 1024) -> Path:
    """Run real traffic through a LiveHub and a SessionRecorder; return the recorded file."""
    hub = LiveHub()
    prepare(hub)
    recorder = SessionRecorder(tmp_path / "rec", max_bytes=max_bytes)
    hub.add_listener(recorder.record)
    recorder.start("rt", hub.snapshot()["robots"])
    publish(hub)
    if recorder.status():
        recorder.stop()
    return next((tmp_path / "rec").glob("*.jsonl"))


def fleet(hub):
    for i in range(150):
        state = {**STATE, "serialNumber": f"r{i}", "information": [{"infoType": "t", "infoDescription": "é" * 700}]}
        state["nodeStates"] = [{"nodeId": f"n{k}", "sequenceId": k * 2, "released": True} for k in range(20)]
        hub.handle_mqtt(f"uagv/v2/ActuNode/r{i}/state", json.dumps(state, ensure_ascii=False).encode())


def hostile(hub):
    publish = lambda payload: hub.handle_mqtt(TOPIC, payload)  # noqa: E731
    publish(json.dumps({**STATE, "text": "päck ünïcode 日本語 🚚"}, ensure_ascii=False).encode())
    publish(b"\xff" * MAX_PAYLOAD_BYTES)  # invalid UTF-8, each byte becomes a 6-byte escape
    publish(b"x" * (MAX_PAYLOAD_BYTES + 10))
    publish(b'{"a": NaN}')
    publish(b"[" * 100 + b"]" * 100)
    publish(
        json.dumps(
            {**STATE, "information": [{"infoType": "x", "infoDescription": "é" * 100000}]}, ensure_ascii=False
        ).encode()
    )


def upload(client, path):
    return client.post("/api/sessions/upload", content=path.read_bytes())


def test_a_recorded_150_robot_snapshot_is_accepted(client, tmp_path):
    path = record(tmp_path, lambda hub: None, prepare=fleet)

    assert len(json.loads(path.read_text().splitlines()[1])["robots"]) == 150
    assert upload(client, path).status_code == 201


def test_recorded_hostile_traffic_is_accepted(client, tmp_path):
    path = record(tmp_path, hostile)

    response = upload(client, path)

    assert response.status_code == 201, response.text
    assert response.json()["messageCount"] == 6


REJECTIONS = {"invalid-json", "payload-too-large", "non-finite-number", "too-deep"}


def test_offline_validation_matches_live_message_by_message(tmp_path):
    live = LiveHub()
    path = record(tmp_path, hostile)
    hostile(live)
    live_rules = [[i["rule"] for i in m["issues"] if i["rule"] in REJECTIONS] for m in live.snapshot()["messages"]]

    offline = validate_session(path)
    by_line = {}
    for item in offline["issues"]:
        if item["rule"] in REJECTIONS:
            by_line.setdefault(item["line"], []).append(item["rule"])

    assert [rules for rules in live_rules if rules] == [by_line[line] for line in sorted(by_line)]
    assert [r for rules in live_rules for r in rules] == [
        "invalid-json",
        "payload-too-large",
        "non-finite-number",
        "too-deep",
    ]


def test_rejected_messages_are_recorded_with_the_rule_that_rejected_them(tmp_path):
    path = record(tmp_path, hostile)

    messages = [json.loads(line) for line in path.read_text().splitlines()]
    messages = [m for m in messages if m["type"] == "message"]

    assert [m.get("rejected") for m in messages] == [
        None,
        "invalid-json",
        "payload-too-large",
        "non-finite-number",
        "too-deep",
        None,
    ]
    assert len(messages[2]["payloadRaw"]) < 2000  # the preview only


def test_older_files_without_the_rejected_field_are_still_reparsed(tmp_path):
    path = record(tmp_path, lambda hub: hub.handle_mqtt(TOPIC, b"x" * 50))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        line.pop("rejected", None)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert [r["rule"] for r in validate_session(path)["byRule"]] == ["invalid-json"]


def test_a_recording_stopped_by_the_size_limit_can_be_uploaded(client, tmp_path, monkeypatch):
    path = record(
        tmp_path,
        lambda hub: [hub.handle_mqtt(TOPIC, json.dumps(STATE).encode()) for _ in range(20)],
        max_bytes=4000,
    )
    # A recording stopped at the cap, whose end record was written past it: the upload limit is the cap.
    cap = path.stat().st_size - 50
    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, max_session_mb=cap / 1024 / 1024))

    assert upload(client, path).status_code == 201
