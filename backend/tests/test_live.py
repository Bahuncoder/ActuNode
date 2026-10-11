import json

import pytest
from fastapi.testclient import TestClient

from app.live import LiveHub, hub
from app.main import app
from app.mqtt_state import mqtt_bridge


def state(serial, status="IDLE", x=1.0):
    return json.dumps(
        {
            "serialNumber": serial,
            "agvPosition": {"x": x, "y": 2.0},
            "actunode": {"missionStatus": status},
        }
    ).encode()


def test_hub_tracks_latest_state_and_connection_per_robot():
    live = LiveHub()

    live.handle_mqtt("uagv/v2/ActuNode/robot_01/connection", b'{"connectionState": "ONLINE"}')
    live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", state("robot_01", x=1.0))
    live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", state("robot_01", "MOVING", x=2.0))

    robot = live.robot("robot_01")
    assert robot["connection"] == "ONLINE"
    assert robot["state"]["agvPosition"]["x"] == 2.0
    assert robot["state"]["actunode"]["missionStatus"] == "MOVING"


def test_same_serial_under_another_manufacturer_or_version_is_another_robot():
    """Serial numbers are unique per manufacturer only (issue 19)."""
    live = LiveHub()

    live.handle_mqtt("uagv/v2/VendorA/robot_01/state", state("robot_01", "MOVING", x=1.0))
    live.handle_mqtt("uagv/v2/VendorB/robot_01/state", state("robot_01", "IDLE", x=5.0))
    live.handle_mqtt("uagv/v3/VendorA/robot_01/state", state("robot_01", "IDLE", x=9.0))

    robots = live.snapshot()["robots"]
    assert [r["key"] for r in robots] == ["v2/VendorA/robot_01", "v2/VendorB/robot_01", "v3/VendorA/robot_01"]
    assert {r["robotId"] for r in robots} == {"robot_01"}
    by_key = {r["key"]: r for r in robots}
    assert by_key["v2/VendorA/robot_01"]["state"]["actunode"]["missionStatus"] == "MOVING"
    assert by_key["v2/VendorB/robot_01"]["state"]["agvPosition"]["x"] == 5.0
    assert by_key["v3/VendorA/robot_01"]["vdaMajor"] == "v3"
    # Lookups by serial: every entry, most recently heard first.
    assert [r["key"] for r in live.robots_for("robot_01")][0] == "v3/VendorA/robot_01"
    assert live.robot("robot_01")["key"] == "v3/VendorA/robot_01"


def test_hub_keeps_invalid_json_in_the_log_without_touching_robots():
    live = LiveHub()

    live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", b"{broken")

    [message] = live.snapshot()["messages"]
    assert message["validJson"] is False
    assert message["payload"] == "{broken"
    assert live.robot("robot_01") is None


def test_order_messages_are_logged_but_do_not_create_state():
    live = LiveHub()

    live.handle_mqtt("uagv/v2/ActuNode/robot_01/order", b'{"orderId": "o1"}')

    assert len(live.snapshot()["messages"]) == 1
    assert live.robot("robot_01")["state"] is None


def test_message_ids_increase():
    live = LiveHub()
    for _ in range(3):
        live.handle_mqtt("uagv/v2/ActuNode/robot_01/state", state("robot_01"))

    ids = [m["id"] for m in live.snapshot()["messages"]]
    assert ids == [1, 2, 3]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "start", lambda: None)
    monkeypatch.setattr(mqtt_bridge, "stop", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


def test_websocket_sends_snapshot_then_live_messages(client):
    hub.handle_mqtt("uagv/v2/ActuNode/robot_ws/state", state("robot_ws"))

    with client.websocket_connect("/api/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert "robot_ws" in [r["robotId"] for r in snapshot["robots"]]

        hub.handle_mqtt("uagv/v2/ActuNode/robot_ws/state", state("robot_ws", "MOVING"))
        event = ws.receive_json()

    assert event["type"] == "message"
    assert event["robot"]["state"]["actunode"]["missionStatus"] == "MOVING"


def test_robot_list_is_capped_by_evicting_the_longest_silent():
    from app import live as live_module

    hub_ = LiveHub()
    original = live_module.MAX_ROBOTS
    live_module.MAX_ROBOTS = 5
    try:
        for i in range(8):
            hub_.handle_mqtt(f"uagv/v2/ActuNode/flood_{i}/state", json.dumps({"serialNumber": f"flood_{i}"}).encode())
        hub_.handle_mqtt("uagv/v2/ActuNode/flood_3/state", b'{"serialNumber": "flood_3"}')  # heard again
        hub_.handle_mqtt("uagv/v2/ActuNode/flood_8/state", b'{"serialNumber": "flood_8"}')
    finally:
        live_module.MAX_ROBOTS = original

    ids = {robot["robotId"] for robot in hub_.snapshot()["robots"]}
    assert len(ids) == 5
    assert "flood_8" in ids and "flood_3" in ids  # newest and recently re-heard survive
    assert "flood_0" not in ids  # longest silent was evicted
