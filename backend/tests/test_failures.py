import json

import pytest
from fastapi.testclient import TestClient

from app.live import hub
from app.main import app
from app.mqtt_state import mqtt_bridge


def report(robot_id, status, connection="ONLINE"):
    hub.handle_mqtt(f"uagv/v2/ActuNode/{robot_id}/connection", json.dumps({"connectionState": connection}).encode())
    hub.handle_mqtt(
        f"uagv/v2/ActuNode/{robot_id}/state",
        json.dumps({"serialNumber": robot_id, "actunode": {"missionStatus": status}}).encode(),
    )


@pytest.fixture
def published(monkeypatch):
    messages = []
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "connected", True)
    monkeypatch.setattr(
        mqtt_bridge,
        "publish",
        lambda topic, payload, qos=0: messages.append((topic, json.loads(payload))),
    )
    return messages


@pytest.fixture
def client(published):
    with TestClient(app) as test_client:
        yield test_client


def test_blocked_path_is_sent_to_moving_robot_and_logged(client, published):
    report("fail_01", "MOVING")

    response = client.post("/api/failures", json={"robot_id": "fail_01"})

    assert response.status_code == 202
    [(topic, command)] = published
    assert topic == "actunode/v1/sim/fail_01/inject"
    assert command["failure"] == "BLOCKED_PATH"
    assert command["action"] == "inject"
    logged = client.get("/api/failures").json()
    assert logged[-1]["injectionId"] == command["injectionId"]
    assert logged[-1]["robotStatus"] == "MOVING"


def test_clear_is_sent_to_blocked_robot(client, published):
    report("fail_02", "BLOCKED")

    response = client.post("/api/failures", json={"robot_id": "fail_02", "action": "clear"})

    assert response.status_code == 202
    assert published[0][1]["action"] == "clear"


@pytest.mark.parametrize("status, action", [("IDLE", "inject"), ("COMPLETED", "inject"), ("MOVING", "clear")])
def test_failure_that_cannot_apply_is_refused(client, published, status, action):
    report("fail_03", status)

    response = client.post("/api/failures", json={"robot_id": "fail_03", "action": action})

    assert response.status_code == 409
    assert status in response.json()["detail"]
    assert published == []


def test_offline_robot_is_refused(client, published):
    report("fail_04", "MOVING", connection="CONNECTIONBROKEN")

    response = client.post("/api/failures", json={"robot_id": "fail_04"})

    assert response.status_code == 409
    assert "CONNECTIONBROKEN" in response.json()["detail"]


def test_unknown_robot_and_failure_are_refused(client, published):
    assert client.post("/api/failures", json={"robot_id": "ghost"}).status_code == 404
    assert client.post("/api/failures", json={"robot_id": "ghost", "failure": "METEOR"}).status_code == 422
    assert published == []


def test_failure_is_pushed_to_live_clients(client, published):
    report("fail_05", "MOVING")

    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()  # snapshot
        client.post("/api/failures", json={"robot_id": "fail_05"})
        event = ws.receive_json()
        while event["type"] != "failure":
            event = ws.receive_json()

    assert event["failure"]["robotId"] == "fail_05"
