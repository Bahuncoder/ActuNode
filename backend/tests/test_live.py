import json

import pytest
from fastapi.testclient import TestClient

from app.live import LiveHub, hub
from app.main import app
from app.mqtt_state import mqtt_bridge
from app.validator import RULES


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
    assert live.robot("robot_01") is None  # command traffic creates no ghost robot


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


T_STATE = "uagv/v2/ActuNode/robot_01/state"


@pytest.mark.parametrize(
    "payload",
    [b'{"batteryState":"x"}', b'{"actunode":1}', b'{"nodes":5}'],
)
def test_wrong_shaped_payload_is_still_logged_and_counted(payload):
    live = LiveHub()

    live.handle_mqtt(T_STATE, payload)

    assert live.validation()["checked"] == 1
    assert len(live.snapshot()["messages"]) == 1


def test_validator_crash_becomes_an_issue_not_a_lost_message(monkeypatch):
    live = LiveHub()

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(live._validator, "check", boom)
    live.handle_mqtt(T_STATE, b"{}")

    [message] = live.snapshot()["messages"]
    assert [i["rule"] for i in message["issues"]] == ["validator-error"]
    assert live.validation()["checked"] == 1


@pytest.mark.parametrize(
    "payload, rule",
    [
        (b"[" * 100000, "too-deep"),
        (b"[" * 600 + b"]" * 600, "too-deep"),
        (b'{"a": NaN}', "non-finite-number"),
        (b'{"a": -Infinity}', "non-finite-number"),
        (b"{oops", "invalid-json"),
        (b"\xff\xfe", "invalid-json"),
        (b'{"a": "' + b"x" * (256 * 1024) + b'"}', "payload-too-large"),
    ],
)
def test_rejected_payloads_are_logged_with_a_precise_rule_and_do_not_update_robots(payload, rule):
    live = LiveHub()

    live.handle_mqtt(T_STATE, payload)

    [message] = live.snapshot()["messages"]
    assert message["validJson"] is False
    assert isinstance(message["payload"], str)
    assert [i["rule"] for i in message["issues"]] == [rule]
    assert rule in RULES
    assert live.snapshot()["robots"] == []
    json.dumps(live.snapshot(), allow_nan=False)  # still serializable


def test_oversized_payload_keeps_only_a_small_preview():
    live = LiveHub()

    live.handle_mqtt(T_STATE, b"x" * (300 * 1024))

    [message] = live.snapshot()["messages"]
    assert len(message["payload"]) < 2048
    assert "307200 bytes" in message["payload"]


def test_large_payload_is_previewed_for_display_but_listeners_get_it_whole():
    live = LiveHub()
    heard = []
    live.add_listener(heard.append)
    big = json.dumps({"serialNumber": "robot_01", "pad": "x" * 20000}).encode()

    live.handle_mqtt(T_STATE, big)

    [shown] = live.snapshot()["messages"]
    [full] = heard
    assert isinstance(shown["payload"], str) and "truncated for display" in shown["payload"]
    assert full["payload"]["pad"] == "x" * 20000
    assert full["id"] == shown["id"] and full["validJson"] is True
    assert live.robot("robot_01")["state"]["pad"] == "x" * 20000


def test_normal_depth_and_finite_numbers_still_pass():
    live = LiveHub()

    live.handle_mqtt(T_STATE, b'{"serialNumber": "robot_01", "a": [[[1.5, -2]]]}')

    assert live.snapshot()["messages"][0]["validJson"] is True


def test_command_traffic_does_not_create_or_evict_robots():
    live = LiveHub()
    live.handle_mqtt(T_STATE, state("robot_01"))

    live.handle_mqtt("uagv/v2/ActuNode/ghost/order", b'{"orderId": "o"}')
    for i in range(1001):
        live.handle_mqtt(f"uagv/v2/ActuNode/x{i}/instantActions", b"{}")

    assert [r["key"] for r in live.snapshot()["robots"]] == ["v2/ActuNode/robot_01"]


def test_message_ids_are_unique_and_sequential_under_rejection():
    live = LiveHub()
    live.handle_mqtt(T_STATE, b"{oops")
    live.handle_mqtt(T_STATE, state("robot_01"))

    assert [m["id"] for m in live.snapshot()["messages"]] == [1, 2]
