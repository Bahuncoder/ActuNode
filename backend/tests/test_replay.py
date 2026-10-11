import asyncio
import json
import time
import tracemalloc

import pytest
from fastapi.testclient import TestClient

from app import sessions
from app.live import hub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.replay import Replayer, ReplayError, is_command, iter_plan, scan_session

STATE = {"headerId": 5, "manufacturer": "ActuNode", "serialNumber": "rp_01", "actunode": {"missionStatus": "IDLE"}}


def write_session(path, messages, robots=None, header=True):
    lines = []
    if header:
        lines.append({"type": "session", "formatVersion": 1, "sessionId": path.stem, "name": None, "startedAt": "x"})
    lines.append(
        {
            "type": "snapshot",
            "robots": robots
            if robots is not None
            else [
                {"robotId": "rp_01", "connection": "ONLINE", "state": STATE, "lastSeen": "x"},
            ],
        }
    )
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


def plan_for(path, include_commands=False):
    scan = scan_session(path)
    return list(iter_plan(path, scan["robots"], include_commands))


def test_commands_are_recognised():
    assert is_command("uagv/v2/ActuNode/r/order")
    assert is_command("uagv/v2/ActuNode/r/instantActions")
    assert is_command("actunode/v1/sim/r/inject")
    assert is_command("uagv/v3/ActuNode/r/zoneSet")
    assert is_command("uagv/v3/ActuNode/r/responses")
    assert not is_command("uagv/v2/ActuNode/r/state")
    assert not is_command("uagv/v2/ActuNode/r/connection")


def test_plan_starts_with_snapshot_and_skips_commands_by_default(tmp_path):
    plan = plan_for(write_session(tmp_path / "20261009-120000.jsonl", MESSAGES), include_commands=False)

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
    path = write_session(tmp_path / "20261009-120000.jsonl", MESSAGES)

    plan = plan_for(path, include_commands=True)

    assert [t for t, _, _ in plan] == [0.0, 0.0, 0.0, 0.02, 0.04, 0.06]
    scan = scan_session(path)
    assert scan["robotIds"] == {"v2/ActuNode/rp_01"}  # topics and an old snapshot entry without vdaMajor agree
    assert scan["count"] == {False: 2, True: 4}
    assert scan["lastT"] == {False: 0.06, True: 0.06}


def test_scan_keeps_manufacturers_and_versions_apart(tmp_path):
    messages = [
        {"t": 0.0, "topic": "uagv/v3/Other/rp_01/state", "payload": {}},
        {"t": 0.1, "topic": "uagv/v2/ActuNode/rp_02/state", "payload": {}},
    ]
    robots = [{"key": "v2/Acme/rp_03", "robotId": "rp_03", "vdaMajor": "v2", "manufacturer": "Acme", "state": {}}]
    path = write_session(tmp_path / "20261009-120000.jsonl", messages, robots=robots)

    assert scan_session(path)["robotIds"] == {"v3/Other/rp_01", "v2/ActuNode/rp_02", "v2/Acme/rp_03"}


def test_file_without_header_is_rejected(tmp_path):
    path = write_session(tmp_path / "20261009-120000.jsonl", MESSAGES, header=False)

    with pytest.raises(ReplayError):
        scan_session(path)


def test_replay_memory_does_not_grow_with_file_size(tmp_path):
    """A ~25 MB session is scanned and streamed with a few MB of memory, not loaded whole."""
    path = tmp_path / "20261009-120000_big.jsonl"
    with path.open("w") as file:
        file.write(json.dumps({"type": "session", "formatVersion": 1, "sessionId": path.stem, "startedAt": "x"}) + "\n")
        file.write(json.dumps({"type": "snapshot", "robots": []}) + "\n")
        for i in range(60_000):
            message = {
                "type": "message",
                "t": i * 0.01,
                "topic": "uagv/v2/ActuNode/rp_01/state",
                "payload": {"i": i, "pad": "x" * 300},
            }
            file.write(json.dumps(message) + "\n")
    assert path.stat().st_size > 20_000_000

    tracemalloc.start()
    scan = scan_session(path)
    streamed = sum(1 for _ in iter_plan(path, scan["robots"], include_commands=False))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert streamed == scan["count"][False] == 60_000
    assert peak < 5_000_000, f"peak memory {peak / 1e6:.1f} MB for a {path.stat().st_size / 1e6:.0f} MB file"


def run(coro):
    return asyncio.run(coro)


def test_replayer_keeps_timing_scaled_by_speed(tmp_path):
    path = write_session(
        tmp_path / "20261009-120000.jsonl",
        [
            {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
            {"t": 0.4, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
        ],
        robots=[],
    )
    sent = []
    statuses = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(time.monotonic()), statuses.append)
        replayer.start("s", path, scan_session(path), speed=2.0, include_commands=False)
        await replayer._task
        return replayer.status()

    status = run(main())

    assert status["state"] == "finished"
    assert status["sent"] == 2
    assert sent[1] - sent[0] == pytest.approx(0.2, abs=0.05)
    assert statuses[-1]["state"] == "finished"


def test_replayer_can_be_stopped(tmp_path):
    path = write_session(
        tmp_path / "20261009-120000.jsonl",
        [
            {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
            {"t": 30.0, "topic": "uagv/v2/ActuNode/rp_01/state", "payload": {}},
        ],
        robots=[],
    )
    sent = []

    async def main():
        replayer = Replayer(lambda topic, payload: sent.append(topic), lambda status: None)
        replayer.start("s", path, scan_session(path), speed=1.0, include_commands=False)
        with pytest.raises(ReplayError):
            replayer.start("s", path, scan_session(path), speed=1.0, include_commands=False)
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


def test_same_serial_from_another_manufacturer_does_not_block_replay(client, published, tmp_path):
    messages = [{"t": 0.0, "topic": "uagv/v2/ActuNode/rp_07/state", "payload": {}}]
    write_session(tmp_path / "20261009-120000_other.jsonl", messages, robots=[])
    hub.handle_mqtt("uagv/v3/Other/rp_07/state", b"{}")

    response = client.post("/api/sessions/20261009-120000_other/replay", json={"speed": 20})

    assert response.status_code == 202
    wait_for_replay(client)


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


def test_session_cannot_be_deleted_while_it_is_replayed(client, published, tmp_path):
    long = [
        {"t": 0.0, "topic": "uagv/v2/ActuNode/rp_08/state", "payload": {}},
        {"t": 30.0, "topic": "uagv/v2/ActuNode/rp_08/state", "payload": {}},
    ]
    write_session(tmp_path / "20261009-120000_busy.jsonl", long, robots=[])
    client.post("/api/sessions/20261009-120000_busy/replay")

    response = client.delete("/api/sessions/20261009-120000_busy")
    client.post("/api/replay/stop")

    assert response.status_code == 409
    assert "replayed" in response.json()["detail"]


def test_replay_restores_each_robot_on_its_own_version_topic():
    from app.replay import snapshot_plan

    robots = [
        {"robotId": "r2", "vdaMajor": "v2", "manufacturer": "ActuNode", "connection": "ONLINE", "state": STATE},
        {"robotId": "r3", "vdaMajor": "v3", "manufacturer": "VendorX", "connection": "ONLINE", "state": STATE},
        {"robotId": "old", "connection": "ONLINE", "state": STATE},  # sessions recorded before vdaMajor existed
    ]

    topics = [topic for _, topic, _ in snapshot_plan(robots)]

    assert "uagv/v2/ActuNode/r2/state" in topics
    assert "uagv/v3/VendorX/r3/state" in topics
    assert "uagv/v2/ActuNode/old/state" in topics
