import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.live import hub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.replay import Replayer, ReplayError, build_plan, is_command, load_session, robot_ids

STATE = {"headerId": 5, "manufacturer": "ActuNode", "serialNumber": "rp_01", "actunode": {"missionStatus": "IDLE"}}


def write_session(path, messages, robots=None, header=True):
    lines = []
    if header:
        lines.append({"type": "session", "formatVersion": 1, "sessionId": path.stem, "name": None, "startedAt": "x"})
    lines.append({"type": "snapshot", "robots": robots if robots is not None else [
        {"robotId": "rp_01", "connection": "ONLINE", "state": STATE, "lastSeen": "x"},
    ]})
    lines += [{"type": "message", "receivedAt": "x", "retained": False, **m} for m in messages]
    lines.append({"type": "end", "endedAt": "x", "messageCount": len(messages)})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


MESSAGES = [
    {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_01/order", "payload": {"orderId": "o1"}},
    {"t": 0.02, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {"actunode": {"missionStatus": "MOVING"}}},
    {"t": 0.04, "topic": "actunode/v1/sim/rp_01/inject", "payload": {"failure": "BLOCKED_PATH"}},
    {"t": 0.06, "topic": "uagv/v2/ActuNode/rp_01/state", "payloadRaw": "{broken"},
]


def test_commands_are_recognised():
    assert is_command("uagv/v2/ActuNode/r/order")
    assert is_command("uagv/v2/ActuNode/r/instantActions")
    assert is_command("actunode/v1/sim/r/inject")
    assert not is_command("uagv/v2/ActuNode/r/state")
    assert not is_command("uagv/v2/ActuNode/r/connection")


def test_plan_starts_with_snapshot_and_skips_commands_by_default(tmp_path):
    session = load_session(write_session(tmp_path / "20261009-120000.jsonl", MESSAGES))

    plan = build_plan(session, include_commands=False)

    topics = [topic for _, topic, _ in plan]
    assert topics == [
        "uagv/v2/ActuNode/rp_01/connection",
        "uagv/v2/ActuNode/rp_01/state",
        "uagv/v2/ActuNode/rp_01/state",
        "uagv/v2/ActuNode/rp_01/state",
    ]
    assert json.loads(plan[0][2])["connectionState"] == "ONLINE"
    assert plan[-1][2] == "{broken"  # invalid payloads are replayed verbatim


def test_plan_with_commands_keeps_everything_in_order(tmp_path):
    session = load_session(write_session(tmp_path / "20261009-120000.jsonl", MESSAGES))

    plan = build_plan(session, include_commands=True)

    assert [t for t, _, _ in plan] == [0.0, 0.0, 0.0, 0.02, 0.04, 0.06]
    assert robot_ids(session) == {"rp_01"}


def test_file_without_header_is_rejected(tmp_path):
    path = write_session(tmp_path / "20261009-120000.jsonl", MESSAGES, header=False)

    with pytest.raises(ReplayError):
        load_session(path)


def run(coro):
    return asyncio.run(coro)


def test_replayer_keeps_timing_scaled_by_speed(tmp_path):
    session = load_session(write_session(tmp_path / "20261009-120000.jsonl", [
        {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
        {"t": 0.4, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
    ], robots=[]))
    sent = []
    statuses = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(time.monotonic()), statuses.append)
        replayer.start("s", session, speed=2.0, include_commands=False)
        await replayer._task
        return replayer.status()

    status = run(main())

    assert status["state"] == "finished"
    assert status["sent"] == 2
    assert sent[1] - sent[0] == pytest.approx(0.2, abs=0.05)
    assert statuses[-1]["state"] == "finished"


def test_replayer_can_be_stopped(tmp_path):
    session = load_session(write_session(tmp_path / "20261009-120000.jsonl", [
        {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
        {"t": 30.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
    ], robots=[]))
    sent = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(topic), lambda status: None)
        replayer.start("s", session, speed=1.0, include_commands=False)
        with pytest.raises(ReplayError):
            replayer.start("s", session, speed=1.0, include_commands=False)
        await asyncio.sleep(0.05)
        replayer.stop()
        await asyncio.gather(replayer._task, return_exceptions=True)
        return replayer.status()

    status = run(main())

    assert status["state"] == "stopped"
    assert sent == ["uagv/v2/ActuNode/rp_01/state"]


@pytest.fixture
def published(monkeypatch, tmp_path):
    messages = []
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: messages.append(topic))
    monkeypatch.setattr(sessions.recorder, "directory", tmp_path)
    monkeypatch.setattr(sessions.replayer, "ended_at", None)
    return messages


@pytest.fixture
def client(published):
    with TestClient(app) as test_client:
        yield test_client


def wait_for_replay(client, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/replay").json()["replay"]
        if status and status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("replay did not finish")


def test_replay_via_api(client, published, tmp_path):
    write_session(tmp_path / "20261009-120000_api.jsonl", MESSAGES, robots=[])

    response = client.post("/api/sessions/20261009-120000_api/replay", json={"speed": 20})

    assert response.status_code == 202
    assert response.json()["includeCommands"] is False
    status = wait_for_replay(client)
    assert status["state"] == "finished"
    assert published == ["uagv/v2/ActuNode/rp_01/state", "uagv/v2/ActuNode/rp_01/state"]


def test_replay_refused_while_robot_is_live(client, published, tmp_path):
    write_session(tmp_path / "20261009-120000_live.jsonl", MESSAGES)
    hub.handle_mqtt("uagv/v2/ActuNode/rp_01/state", json.dumps(STATE).encode())

    response = client.post("/api/sessions/20261009-120000_live/replay")

    assert response.status_code == 409
    assert "rp_01 is publishing live state" in response.json()["detail"]
    assert published == []


def test_retained_offline_connection_does_not_count_as_live(client, published, tmp_path):
    # rp_09 is used by no other test; the hub is shared across tests.
    messages = [{"t": 0.0, "topic": "uagv/v2/ActuNode/rp_09/state", "payload": {}}]
    write_session(tmp_path / "20261009-120000_retained.jsonl", messages, robots=[])
    hub.handle_mqtt("uagv/v2/ActuNode/rp_09/connection", b'{"connectionState": "OFFLINE"}', retained=True)

    response = client.post("/api/sessions/20261009-120000_retained/replay", json={"speed": 20})

    assert response.status_code == 202
    wait_for_replay(client)


def test_replay_refuses_unknown_and_recording_sessions(client, published):
    assert client.post("/api/sessions/20261009-120000_nope/replay").status_code == 404

    session_id = client.post("/api/recording/start", json={"name": "busy"}).json()["sessionId"]
    response = client.post(f"/api/sessions/{session_id}/replay")
    client.post("/api/recording/stop")

    assert response.status_code == 409


def test_stop_without_replay_is_refused(client, published):
    if sessions.replayer.running:
        sessions.replayer.stop()
    assert client.post("/api/replay/stop").status_code == 409
