import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.replay import Replayer, scan_session, with_current_time
from tests.test_replay import run, wait_for_replay, write_session

OLD = "2020-01-01T00:00:00.000Z"
STATE_TOPIC = "uagv/v2/ActuNode/ct_01/state"  # own serial: other tests leave rp_01 "live" in the hub
MESSAGES = [
    {"t": 0.0, "topic": STATE_TOPIC, "payload": {"headerId": 1, "timestamp": OLD, "x": "a"}},
    {"t": 0.02, "topic": STATE_TOPIC, "payload": {"headerId": 2, "timestamp": OLD, "x": "b"}},
    {"t": 0.04, "topic": STATE_TOPIC, "payloadRaw": "{broken"},
]


def age(timestamp):
    assert timestamp.endswith("Z")
    return abs((datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds())


def test_with_current_time_sets_a_fresh_timestamp_and_keeps_other_fields():
    result = json.loads(with_current_time(json.dumps({"headerId": 7, "timestamp": OLD, "nested": {"a": [1]}})))

    assert age(result.pop("timestamp")) < 2
    assert result == {"headerId": 7, "nested": {"a": [1]}}


@pytest.mark.parametrize("payload", ["{broken", "", "[1, 2]", '[{"timestamp": "x"}]', '{"headerId": 1}', "5", "null"])
def test_with_current_time_leaves_everything_else_unchanged(payload):
    assert with_current_time(payload) == payload


def replay_payloads(path, current_time):
    sent = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append((topic, payload)), lambda status: None)
        replayer.start("s", path, scan_session(path), 20, False, current_time=current_time)
        status = replayer.status()
        await replayer._task
        return status, replayer.status()

    return sent, *run(main())


def test_replay_with_current_time_publishes_current_timestamps(tmp_path):
    path = write_session(tmp_path / "a.jsonl", MESSAGES, robots=[])

    sent, started, final = replay_payloads(path, True)

    assert started["currentTime"] is True and final["currentTime"] is True
    assert [topic for topic, _ in sent] == [STATE_TOPIC] * 3
    first, second = (json.loads(payload) for _, payload in sent[:2])
    assert age(first.pop("timestamp")) < 2 and age(second.pop("timestamp")) < 2
    assert first == {"headerId": 1, "x": "a"} and second == {"headerId": 2, "x": "b"}
    assert sent[2][1] == "{broken"


def test_replay_without_current_time_keeps_recorded_timestamps(tmp_path):
    path = write_session(tmp_path / "b.jsonl", MESSAGES, robots=[])

    sent, started, final = replay_payloads(path, False)

    assert started["currentTime"] is False and final["currentTime"] is False
    assert [json.loads(p)["timestamp"] for _, p in sent[:2]] == [OLD, OLD]
    assert sent[2][1] == "{broken"


@pytest.fixture
def payloads(monkeypatch, tmp_path):
    messages = []
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: messages.append(payload))
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    monkeypatch.setattr(sessions.replayer, "ended_at", None)
    return messages


def test_api_passes_current_time_through(payloads, tmp_path):
    write_session(tmp_path / "20261009-120000_ct.jsonl", MESSAGES, robots=[])
    with TestClient(app) as client:
        response = client.post("/api/sessions/20261009-120000_ct/replay", json={"speed": 20, "current_time": True})
        assert response.status_code == 202, response.text
        assert response.json()["currentTime"] is True
        assert wait_for_replay(client)["currentTime"] is True
    assert age(json.loads(payloads[0])["timestamp"]) < 2


def test_api_defaults_current_time_off(payloads, tmp_path):
    write_session(tmp_path / "20261009-120000_ct2.jsonl", MESSAGES, robots=[])
    with TestClient(app) as client:
        response = client.post("/api/sessions/20261009-120000_ct2/replay", json={"speed": 20})
        assert response.json()["currentTime"] is False
        wait_for_replay(client)
    assert json.loads(payloads[0])["timestamp"] == OLD


@pytest.mark.parametrize("value", ["maybe", [1], {"a": 1}, None])
def test_api_rejects_non_boolean_current_time(payloads, tmp_path, value):
    write_session(tmp_path / "20261009-120000_ct3.jsonl", MESSAGES, robots=[])
    with TestClient(app) as client:
        response = client.post("/api/sessions/20261009-120000_ct3/replay", json={"current_time": value})
    assert response.status_code == 422
