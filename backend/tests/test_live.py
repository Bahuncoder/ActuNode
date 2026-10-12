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
    assert event["message"]["payload"]["actunode"]["missionStatus"] == "MOVING"
    assert event["robot"]["stateFromMessage"] is True


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


# --- Week 4: lagging clients, proximity throttle, payload sent once, one encoding --------------


def _capture(live):
    events = []
    live.broadcast = events.append
    return events


def _move(live, serial, x, y=0.0):
    body = {"serialNumber": serial, "agvPosition": {"x": x, "y": y, "theta": 0, "mapId": "w"}}
    live.handle_mqtt(f"uagv/v2/ActuNode/{serial}/state", json.dumps(body).encode())


def _fake_clock(live):
    clock = [0.0]
    live._clock = lambda: clock[0]
    live._proximity._now = lambda: clock[0]
    return clock


def test_proximity_broadcasts_when_the_pair_set_changes_and_throttles_distance_changes():
    live = LiveHub()
    clock = _fake_clock(live)
    events = _capture(live)
    pairs = lambda: [e for e in events if e["type"] == "proximity"]  # noqa: E731

    _move(live, "a", 0.0)
    _move(live, "b", 0.5)  # pair appears: immediately
    assert len(pairs()) == 1
    clock[0] = 0.1
    _move(live, "b", 0.4)  # only the distance changed, inside the refresh interval
    _move(live, "b", 0.3)
    assert len(pairs()) == 1
    clock[0] = 1.2
    _move(live, "b", 0.2)  # refresh interval passed
    assert len(pairs()) == 2 and pairs()[-1]["pairs"][0]["distance"] == 0.2
    clock[0] = 1.3
    _move(live, "b", 5.0)  # pair gone: immediately, even inside the interval
    assert len(pairs()) == 3 and pairs()[-1]["pairs"] == []
    _move(live, "b", 6.0)  # still nothing close: no event
    assert len(pairs()) == 3


def test_proximity_is_not_recomputed_for_messages_that_cannot_change_it(monkeypatch):
    live = LiveHub()
    calls = []
    original = live._proximity.active_pairs
    live._proximity.active_pairs = lambda: calls.append(1) or original()

    live.handle_mqtt("uagv/v2/ActuNode/r/order", b'{"orderId": "o1"}')
    assert calls == []
    _move(live, "a", 0.0)
    assert len(calls) == 1


def test_state_message_event_sends_the_state_once():
    live = LiveHub()
    events = _capture(live)

    live.handle_mqtt("uagv/v2/ActuNode/r1/state", state("r1", "MOVING"))
    live.handle_mqtt("uagv/v2/ActuNode/r1/connection", b'{"connectionState": "ONLINE"}')

    state_event, connection_event = [e for e in events if e["type"] == "message"]
    assert state_event["message"]["payload"]["actunode"]["missionStatus"] == "MOVING"
    assert "state" not in state_event["robot"] and state_event["robot"]["stateFromMessage"] is True
    assert state_event["robot"]["robotId"] == "r1"
    assert connection_event["robot"]["state"]["actunode"]["missionStatus"] == "MOVING"
    assert "stateFromMessage" not in connection_event["robot"]
    assert live.snapshot()["robots"][0]["state"] is not None  # snapshot keeps state


def test_previewed_state_message_keeps_robot_state():
    live = LiveHub()
    events = _capture(live)
    big = json.dumps({"serialNumber": "r1", "pad": "x" * 20000}).encode()

    live.handle_mqtt("uagv/v2/ActuNode/r1/state", big)

    [event] = [e for e in events if e["type"] == "message"]
    assert isinstance(event["message"]["payload"], str)
    assert event["robot"]["state"]["serialNumber"] == "r1"
    assert "stateFromMessage" not in event["robot"]


def test_slow_client_is_marked_lagged_once_and_gets_only_the_sentinel(monkeypatch, caplog):
    from app import live as live_module

    monkeypatch.setattr(live_module, "CLIENT_QUEUE", 2)
    live = LiveHub()
    queue = live.subscribe()

    with caplog.at_level("WARNING"):
        for number in range(10):
            live._deliver({"type": "n", "n": number})

    assert [queue.get_nowait() for _ in range(queue.qsize())] == [live_module.LAGGED]
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_slow_websocket_client_is_closed_with_1013(client, monkeypatch, caplog):
    from starlette.websockets import WebSocketDisconnect

    from app import live as live_module

    monkeypatch.setattr(live_module, "CLIENT_QUEUE", 1)
    with caplog.at_level("WARNING"), client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        # One loop callback, so the handler cannot drain the queue in between.
        hub._loop.call_soon_threadsafe(lambda: [hub._deliver({"type": "n", "n": n}) for n in range(20)])
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1013
    assert "lagging" in closed.value.reason
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_broadcast_encodes_once_and_all_clients_get_the_same_text():
    live = LiveHub()
    first, second = live.subscribe(), live.subscribe()

    live._deliver({"type": "failure", "failure": {"text": "päck", "n": 1.5}})

    a, b = first.get_nowait(), second.get_nowait()
    assert a is b and isinstance(a, str)
    assert json.loads(a) == {"type": "failure", "failure": {"text": "päck", "n": 1.5}}


def test_live_message_event_matches_the_shared_contract_fixture():
    """contracts/live_message_event.json is read by the frontend tests too (frontend/src/live.test.ts), so the
    WebSocket event shape cannot drift between the two sides unnoticed (a mismatch once broke the live view,
    D-38). Regenerate with ACTUNODE_UPDATE_CONTRACTS=1 after a deliberate change."""
    import os
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "contracts" / "live_message_event.json"
    live, events = LiveHub(), []
    live.broadcast = events.append
    live.handle_mqtt("uagv/v2/ActuNode/robot_c/state", state("robot_c", "MOVING", x=4.0))
    event = events[0]
    for volatile in ("receivedAt", "id"):
        event["message"].pop(volatile)
    event["robot"].pop("lastSeen")
    event["robot"].pop("lastStateAt")
    if os.environ.get("ACTUNODE_UPDATE_CONTRACTS"):
        fixture.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n")
    assert json.loads(fixture.read_text()) == json.loads(json.dumps(event))


def _big_state(lists=120, pad=700):
    return {
        "serialNumber": "r1",
        "batteryState": {"batteryCharge": 50.0},
        "nodeStates": [{"nodeId": f"n{i}", "pad": "x" * pad} for i in range(lists)],
        "errors": [],
        "actunode": {"missionStatus": "MOVING"},
    }


def test_big_state_is_stored_reduced_with_a_marker():
    live = LiveHub()
    events = _capture(live)
    raw = json.dumps(_big_state()).encode()
    assert len(raw) > 64 * 1024

    live.handle_mqtt("uagv/v2/ActuNode/r1/state", raw)

    stored = live.snapshot()["robots"][0]["state"]
    assert len(stored["nodeStates"]) == 50
    assert stored["serialNumber"] == "r1" and stored["actunode"] == {"missionStatus": "MOVING"}
    assert stored["_truncated"] == {"bytes": len(raw), "lists": {"nodeStates": 120}}
    [event] = [e for e in events if e["type"] == "message"]
    assert event["robot"]["state"] == stored and "stateFromMessage" not in event["robot"]
    assert isinstance(event["message"]["payload"], str)  # the display preview is unchanged


def test_small_state_is_stored_unchanged():
    live = LiveHub()
    events = _capture(live)
    raw = json.dumps(_big_state(lists=60, pad=10)).encode()
    assert len(raw) < 64 * 1024

    live.handle_mqtt("uagv/v2/ActuNode/r1/state", raw)

    stored = live.snapshot()["robots"][0]["state"]
    assert "_truncated" not in stored and len(stored["nodeStates"]) == 60
    [event] = [e for e in events if e["type"] == "message"]
    assert event["robot"]["stateFromMessage"] is True


def test_stored_state_memory_is_bounded_under_a_flood():
    from app import live as live_module
    from app.jsonsafe import MAX_PAYLOAD_BYTES

    live = LiveHub()
    pad = "x" * 100_000  # a scalar field alone is big: the flood must not get this stored whole
    body = {"serialNumber": "r", "nodeStates": [{"a": 1}] * 10_000, "pad": pad}
    raw = json.dumps(body).encode()
    assert len(raw) <= MAX_PAYLOAD_BYTES
    for i in range(live_module.MAX_ROBOTS):  # straight to the store: validating 1000 huge states is slow
        live._update_robot(f"uagv/v2/ActuNode/r{i}/state", json.loads(raw), "now", len(raw))

    total = sum(len(json.dumps(r["state"])) for r in live.snapshot()["robots"])
    assert len(live.snapshot()["robots"]) == live_module.MAX_ROBOTS
    assert total <= live_module.MAX_ROBOTS * live_module.MAX_STORED_STATE_BYTES


def test_validation_epoch_increments_on_reset():
    live = LiveHub()
    assert live.validation()["epoch"] == 0
    live.reset_validation()
    live.reset_validation()
    assert live.validation()["epoch"] == 2
    assert live.snapshot()["validation"]["epoch"] == 2


def test_message_carries_the_epoch_it_was_counted_under_even_if_broadcast_after_a_reset():
    live = LiveHub()
    events = _capture(live)
    capture = live.broadcast

    def reset_first(event):  # a reset sneaks in between counting the message and broadcasting it
        live.broadcast = capture
        live.reset_validation()
        capture(event)

    live.broadcast = reset_first

    live.handle_mqtt("uagv/v2/ActuNode/r1/state", state("r1"))

    [message] = [e for e in events if e["type"] == "message"]
    assert message["validationEpoch"] == 0
    assert live.validation()["epoch"] == 1


def test_reset_event_carries_the_new_epoch():
    live = LiveHub()
    events = _capture(live)
    live.reset_validation()
    assert events[-1]["validation"]["epoch"] == 1
