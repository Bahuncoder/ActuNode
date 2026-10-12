import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import sent_orders as sent_orders_module
from app import vda5050
from app.live import hub
from app.main import app
from app.mqtt import PayloadTooLarge
from app.mqtt_state import mqtt_bridge
from app.sent_orders import sent_orders
from app.validator import Validator

P1042 = {
    "robot_id": "robot_01",
    "source": "RECEIVING_DOOR_2",
    "destination": "STORAGE_A17",
    "load_id": "P-1042",
}


@pytest.fixture
def published(monkeypatch):
    """Pretend the broker is up and capture what gets published."""
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


def test_pallet_mission_publishes_vda5050_order(client, published):
    response = client.post("/api/missions", json=P1042)

    assert response.status_code == 202
    [(topic, order)] = published
    assert topic == "uagv/v2/ActuNode/robot_01/order"
    assert order["orderId"] == response.json()["order_id"]
    assert [node["nodeId"] for node in order["nodes"]] == ["RECEIVING_DOOR_2", "STORAGE_A17"]
    assert [node["sequenceId"] for node in order["nodes"]] == [0, 2]
    assert order["edges"][0]["sequenceId"] == 1
    assert order["edges"][0]["startNodeId"] == "RECEIVING_DOOR_2"
    pick = order["nodes"][0]["actions"][0]
    assert pick["actionType"] == "pick"
    assert pick["actionParameters"] == [{"key": "loadId", "value": "P-1042"}]
    assert order["nodes"][1]["actions"][0]["actionType"] == "drop"


def test_destination_only_mission_has_one_node_and_no_actions(client, published):
    response = client.post("/api/missions", json={"robot_id": "robot_02", "destination": "CHARGING"})

    assert response.status_code == 202
    order = published[0][1]
    assert len(order["nodes"]) == 1
    assert order["nodes"][0]["actions"] == []
    assert order["edges"] == []


def test_unknown_location_is_rejected(client, published):
    response = client.post("/api/missions", json={**P1042, "destination": "NOWHERE"})

    assert response.status_code == 422
    assert published == []


@pytest.mark.parametrize("robot_id", ["robot/01", "robot_#", "+", ""])
def test_robot_id_cannot_inject_topic_levels(client, published, robot_id):
    response = client.post("/api/missions", json={**P1042, "robot_id": robot_id})

    assert response.status_code == 422
    assert published == []


def test_mission_fails_fast_when_broker_is_down(client, published, monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "connected", False)

    response = client.post("/api/missions", json=P1042)

    assert response.status_code == 503
    assert published == []


def test_locations_are_listed(client, published):
    locations = client.get("/api/locations").json()

    assert "RECEIVING_DOOR_2" in locations
    assert "STORAGE_A17" in locations


def test_orders_are_published_with_qos_0_as_vda5050_requires(client, monkeypatch):
    """VDA 5050 2.1 section 6.2 (and 3.0): order, instantActions and state use QoS 0."""
    qos_used = []
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: qos_used.append(qos))

    client.post("/api/missions", json=P1042)

    assert qos_used == [0]


def _seen(topic: str, payload: dict) -> None:
    """Let the live hub see a robot, as if its state had arrived over MQTT."""
    hub.handle_mqtt(topic, json.dumps(payload).encode())


def test_order_to_a_3_0_robot_uses_the_requested_version_and_passes_the_official_3_0_schema(client, published):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "v3_state.json").read_text())
    _seen(fixture["topic"], fixture["payload"])

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_31", "vda_version": "3"})

    assert response.status_code == 202
    assert "warning" not in response.json()
    [(topic, order)] = published
    assert topic == "uagv/v3/ActuNode/robot_31/order"
    assert order["version"] == "3.0.0"
    assert all("startNodeId" not in edge and "endNodeId" not in edge for edge in order["edges"])
    assert Validator().check(topic, order, valid_json=True) == []


def test_observed_traffic_never_decides_where_orders_go(client, published):
    """Security reviews: anything inferred from anonymous MQTT traffic can be spoofed. Routing is the
    configured default or exactly what the request names; observations only produce a warning."""
    _seen("uagv/v3/Spoofer/robot_s/state", {"serialNumber": "robot_s"})

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_s"})

    assert response.status_code == 202
    assert published[0][0] == "uagv/v2/ActuNode/robot_s/order"
    assert "Spoofer v3" in response.json()["warning"]


def test_explicit_identity_is_used_exactly(client, published):
    client.post("/api/missions", json={**P1042, "robot_id": "amr_1", "manufacturer": "VendorX", "vda_version": "2"})

    [(topic, order)] = published
    assert topic == "uagv/v2/VendorX/amr_1/order"
    assert order["manufacturer"] == "VendorX"
    assert "startNodeId" in order["edges"][0]


def test_no_warning_when_the_robot_was_seen_with_the_identity_used(client, published):
    _seen(
        "uagv/v2/ActuNode/robot_ok/state", {"serialNumber": "robot_ok", "agvPosition": {"x": 1, "y": 2, "mapId": "m"}}
    )

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_ok"})

    assert "warning" not in response.json()


def test_order_to_a_robot_never_seen_uses_the_configured_default(client, published):
    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_unseen"})

    [(topic, order)] = published
    assert topic == "uagv/v2/ActuNode/robot_unseen/order"
    assert order["version"] == "2.1.0"
    assert response.json()["warning"].startswith("robot_unseen has not reported a position yet")


@pytest.mark.parametrize("manufacturer", ["Evil/robot", "a#b", "+", ""])
def test_explicit_manufacturer_cannot_inject_topic_levels(client, published, manufacturer):
    response = client.post("/api/missions", json={**P1042, "manufacturer": manufacturer, "vda_version": "2"})

    assert response.status_code == 422
    assert published == []


def test_warning_lists_every_identity_the_serial_was_seen_under(client, published):
    _seen("uagv/v2/VendorA/robot_dup/state", {"serialNumber": "robot_dup"})
    _seen("uagv/v3/VendorB/robot_dup/state", {"serialNumber": "robot_dup"})

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_dup"})

    [(topic, _)] = published
    assert topic == "uagv/v2/ActuNode/robot_dup/order"  # still the default: observations never route (D-21)
    assert "VendorB v3" in response.json()["warning"] and "VendorA v2" in response.json()["warning"]


def test_every_mission_to_a_robot_seen_under_another_identity_carries_the_warning(client, published):
    """Command traffic (our own orders echoed back over uagv/#) must not hide the D-21 warning."""
    _seen("uagv/v2/Other/robot_w/state", {"serialNumber": "robot_w"})
    for _ in range(2):
        response = client.post("/api/missions", json={**P1042, "robot_id": "robot_w", "vda_version": "3"})
        topic, order = published[-1]
        hub.handle_mqtt(topic, json.dumps(order).encode())  # the broker echoes the order back

        assert "Other v2" in response.json()["warning"]


def _state_with_position(major: str, manufacturer: str, robot_id: str, x=1.5, y=2.5, map_id="warehouse") -> None:
    key = "agvPosition" if major == "v2" else "mobileRobotPosition"
    _seen(
        f"uagv/{major}/{manufacturer}/{robot_id}/state",
        {"serialNumber": robot_id, key: {"x": x, "y": y, "mapId": map_id}},
    )


def _validates(topic: str, message: dict) -> list:
    return Validator().check(topic, message, valid_json=True)


@pytest.mark.parametrize("version,major", [("2", "v2"), ("3", "v3")])
def test_order_starts_where_the_robot_is(client, published, version, major):
    _state_with_position(major, "ActuNode", "robot_st", map_id="floor1")

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_st", "vda_version": version})

    [(topic, order)] = published
    assert "warning" not in response.json()
    start = order["nodes"][0]
    assert start["nodeId"] == f"start-{order['orderId']}"
    assert start["sequenceId"] == 0 and start["released"] is True and start["actions"] == []
    assert start["nodePosition"] == {"x": 1.5, "y": 2.5, "mapId": "floor1"}
    assert [n["sequenceId"] for n in order["nodes"]] == [0, 2, 4]
    assert [e["sequenceId"] for e in order["edges"]] == [1, 3]
    assert _validates(topic, order) == []


def test_start_position_comes_from_the_addressed_identity_only(client, published):
    _state_with_position("v2", "Other", "robot_oi", x=9, y=9)

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_oi"})

    order = published[0][1]
    assert len(order["nodes"]) == 2
    assert "has not reported a position yet" in response.json()["warning"]


def test_order_without_known_position_warns(client, published):
    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_np"})

    assert "robot_np has not reported a position yet; it may reject the order" in response.json()["warning"]
    assert [n["sequenceId"] for n in published[0][1]["nodes"]] == [0, 2]


@pytest.mark.parametrize("version,major", [("2", "v2"), ("3", "v3")])
def test_cancel_publishes_a_valid_cancel_order_instant_action(client, published, version, major):
    response = client.post("/api/missions/robot_c/cancel", json={"vda_version": version, "manufacturer": "Acme"})

    assert response.status_code == 202
    [(topic, message)] = published
    assert topic == f"uagv/{major}/Acme/robot_c/instantActions"
    [action] = message["actions"]
    assert action["actionType"] == "cancelOrder" and action["blockingType"] == "NONE"
    assert action["actionParameters"] == []
    assert response.json() == {"actionId": action["actionId"], "topic": topic}
    assert message["serialNumber"] == "robot_c" and message["manufacturer"] == "Acme"
    assert _validates(topic, message) == []


def test_cancel_without_body_uses_defaults_and_unique_action_ids(client, published):
    first = client.post("/api/missions/robot_c/cancel").json()
    second = client.post("/api/missions/robot_c/cancel").json()

    assert first["topic"] == "uagv/v2/ActuNode/robot_c/instantActions"
    assert first["actionId"] != second["actionId"]
    assert [m["headerId"] for _, m in published] == [1, 2]


@pytest.mark.parametrize("robot_id", ["robot%23", "robot%2F01", "+"])
def test_cancel_rejects_topic_injection(client, published, robot_id):
    assert client.post(f"/api/missions/{robot_id}/cancel").status_code in (404, 422)
    assert published == []
    assert client.post("/api/missions/r1/cancel", json={"manufacturer": "a/b"}).status_code == 422
    assert client.post("/api/missions/r1/cancel", json={"vda_version": "9"}).status_code == 422


def test_cancel_fails_fast_when_broker_is_down(client, published, monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "connected", False)

    assert client.post("/api/missions/robot_c/cancel").status_code == 503


def _robot_state(major, robot_id, order, *, update_id=0, last_seq=0, status="MOVING", manufacturer="ActuNode"):
    """The robot's own state for an order it was sent: nodes after last_seq are still to do."""
    nodes = order["nodes"]
    done = next(n for n in nodes if n["sequenceId"] == last_seq)
    _seen(
        f"uagv/{major}/{manufacturer}/{robot_id}/state",
        {
            "serialNumber": robot_id,
            "orderId": order["orderId"],
            "orderUpdateId": update_id,
            "lastNodeId": done["nodeId"],
            "lastNodeSequenceId": last_seq,
            "nodeStates": [
                {"nodeId": n["nodeId"], "sequenceId": n["sequenceId"], "released": True}
                for n in nodes
                if n["sequenceId"] > last_seq
            ],
            "actunode": {"missionStatus": status},
        },
    )


def _mission(client, robot_id, major="v2", **extra):
    version = major[1:]
    _state_with_position(major, "ActuNode", robot_id)
    return client.post("/api/missions", json={**P1042, "robot_id": robot_id, "vda_version": version, **extra}).json()


def _extend(client, robot_id, to="CHARGING", major="v2", **extra):
    return client.post(f"/api/missions/{robot_id}/extend", json={"to_location": to, "vda_version": major[1:], **extra})


@pytest.mark.parametrize("version,major", [("2", "v2"), ("3", "v3")])
def test_extend_mid_route_stitches_at_the_last_released_node(client, published, version, major):
    sent = _mission(client, "robot_x", major)
    _robot_state(major, "robot_x", sent["order"], last_seq=2)
    published.clear()

    response = _extend(client, "robot_x", major=major)

    assert response.status_code == 202
    [(topic, update)] = published
    assert response.json() == {"orderId": sent["order_id"], "orderUpdateId": 1, "topic": topic}
    assert topic == f"uagv/{major}/ActuNode/robot_x/order"
    assert update["orderId"] == sent["order_id"] and update["orderUpdateId"] == 1
    stitch, new = update["nodes"]
    assert stitch == sent["order"]["nodes"][-1] and stitch["sequenceId"] == 4
    assert new["nodeId"] == "CHARGING" and new["sequenceId"] == 6 and new["released"]
    assert new["actions"][0]["actionType"] == "drop"
    assert update["edges"][0]["sequenceId"] == 5
    assert _validates(topic, update) == []

    # The robot confirms update 1; the next extend continues from the node that update added.
    _robot_state(major, "robot_x", {"orderId": sent["order_id"], "nodes": [stitch, new]}, update_id=1, last_seq=4)
    again = _extend(client, "robot_x", "STORAGE_A17", major)
    assert again.json()["orderUpdateId"] == 2
    assert published[1][1]["nodes"][0]["nodeId"] == "CHARGING"
    assert published[1][1]["nodes"][1]["sequenceId"] == 8


def test_extend_after_completion_stitches_at_the_last_node(client, published):
    sent = _mission(client, "robot_done")
    _robot_state("v2", "robot_done", sent["order"], last_seq=4, status="COMPLETED")
    published.clear()

    assert _extend(client, "robot_done").status_code == 202

    stitch, new = published[0][1]["nodes"]
    assert stitch == sent["order"]["nodes"][-1] and new["sequenceId"] == 6


def _conflict(client, published, robot_id, detail, **extra):
    published.clear()
    response = _extend(client, robot_id, **extra)
    assert response.status_code == 409
    assert detail in response.json()["detail"]
    assert published == []


def test_extend_without_a_robot_state_is_a_conflict(client, published):
    _conflict(client, published, "robot_none", "no state from robot_none")


def test_extend_only_continues_the_order_of_the_same_identity(client, published):
    sent = _mission(client, "robot_y")
    _robot_state("v2", "robot_y", sent["order"], manufacturer="Other")
    _conflict(client, published, "robot_y", "no state from robot_y", manufacturer="Other2")


def test_extend_after_cancel_is_a_conflict(client, published):
    sent = _mission(client, "robot_cx")
    _robot_state("v2", "robot_cx", sent["order"], status="CANCELLED")
    _conflict(client, published, "robot_cx", "order was cancelled; send a new mission")


def test_extend_after_a_rejected_second_mission_targets_the_robots_own_order(client, published):
    first = _mission(client, "robot_two")
    second = _mission(client, "robot_two")  # busy robot rejects it; its state still names the first
    assert first["order_id"] != second["order_id"]
    _robot_state("v2", "robot_two", first["order"], last_seq=2)
    published.clear()

    assert _extend(client, "robot_two").status_code == 202

    assert published[0][1]["orderId"] == first["order_id"]


def test_extend_of_an_order_not_sent_by_this_backend_is_a_conflict(client, published):
    sent = _mission(client, "robot_foreign")
    _robot_state("v2", "robot_foreign", {**sent["order"], "orderId": "someone-else"})
    _conflict(client, published, "robot_foreign", "robot_foreign is running an order ActuNode did not send")


def test_extend_after_a_robot_restart_is_a_conflict(client, published):
    sent = _mission(client, "robot_rs")
    _robot_state("v2", "robot_rs", {**sent["order"], "orderId": ""})
    _conflict(client, published, "robot_rs", "running an order ActuNode did not send")


def test_extend_before_the_robot_confirmed_the_previous_update_is_a_conflict(client, published):
    sent = _mission(client, "robot_unc")
    _robot_state("v2", "robot_unc", sent["order"], last_seq=2)
    assert _extend(client, "robot_unc").status_code == 202  # update 1 sent; the state still says 0
    _conflict(client, published, "robot_unc", "previous update not confirmed by the robot yet; retry in a moment")


def test_concurrent_extends_send_one_update_only(client, published, monkeypatch):
    sent = _mission(client, "robot_cc")
    _robot_state("v2", "robot_cc", sent["order"], last_seq=2)
    published.clear()
    real_publish, real_topic = mqtt_bridge.publish, vda5050.topic
    both_started = threading.Event()
    calls = []

    def counting_topic(*args, **kwargs):  # every extend calls this once, before taking the lock
        calls.append(1)
        if len(calls) == 2:
            both_started.set()
        return real_topic(*args, **kwargs)

    def waiting_publish(topic, payload, qos=0):
        assert both_started.wait(5)  # the other extend is under way while this one holds the lock
        real_publish(topic, payload, qos)

    monkeypatch.setattr(vda5050, "topic", counting_topic)
    monkeypatch.setattr(mqtt_bridge, "publish", waiting_publish)
    with ThreadPoolExecutor(2) as pool:
        codes = sorted(f.result().status_code for f in [pool.submit(_extend, client, "robot_cc") for _ in range(2)])

    assert codes == [202, 409]
    assert [m["orderUpdateId"] for _, m in published] == [1]


def test_extend_rejects_unknown_location_and_action(client, published):
    _mission(client, "robot_z")

    assert _extend(client, "robot_z", "NOWHERE").status_code == 422
    assert _extend(client, "robot_z", action="fly").status_code == 422


def test_remembered_orders_are_capped(client, published, monkeypatch):
    monkeypatch.setattr(sent_orders_module, "MAX_REMEMBERED_ORDERS", 2)
    sents = {}
    for robot in ("ra", "rb", "rc"):
        sents[robot] = _mission(client, robot)
        _robot_state("v2", robot, sents[robot]["order"], last_seq=2)

    _conflict(client, published, "ra", "did not send")
    assert _extend(client, "rc").status_code == 202


# --- review fixes -------------------------------------------------------------------------------


def test_a_rejected_update_does_not_lock_the_robot_out(client, published, monkeypatch):
    sent = _mission(client, "robot_rej")
    _robot_state("v2", "robot_rej", sent["order"], last_seq=2)
    assert _extend(client, "robot_rej").json()["orderUpdateId"] == 1
    published.clear()

    # Update 1 was rejected or lost: the robot still says 0. Right after sending, wait (it may be in flight).
    _conflict(client, published, "robot_rej", "previous update not confirmed by the robot yet; retry in a moment")

    # Once the in-flight window is over, the stale update counts as lost: a fresh one is built from the state.
    now = sent_orders.clock()
    monkeypatch.setattr(sent_orders, "clock", lambda: now + 6)
    response = _extend(client, "robot_rej")

    assert response.status_code == 202
    assert response.json()["orderUpdateId"] == 1  # state (0) + 1, not 2
    assert published[0][1]["orderUpdateId"] == 1


def test_extend_numbers_the_update_from_the_robots_confirmed_state(client, published, monkeypatch):
    sent = _mission(client, "robot_num")
    _robot_state("v2", "robot_num", sent["order"], last_seq=2, update_id=3)  # robot is further along than we know
    published.clear()

    assert _extend(client, "robot_num").json()["orderUpdateId"] == 4


@pytest.mark.parametrize("bad", [["x"], True, 1.5, None, "2"])
@pytest.mark.parametrize("field", ["orderUpdateId", "lastNodeSequenceId", "released"])
def test_extend_rejects_robot_state_fields_of_the_wrong_type(client, published, bad, field):
    sent = _mission(client, "robot_ty")
    _robot_state("v2", "robot_ty", sent["order"], last_seq=2)
    state = dict(hub.robot("robot_ty")["state"])
    if field == "released":  # the decision node's sequenceId, taken from nodeStates
        state["nodeStates"] = [{"sequenceId": bad, "released": True}]
        field = "sequenceId"
    else:
        state[field] = bad
    _seen("uagv/v2/ActuNode/robot_ty/state", state)

    _conflict(client, published, "robot_ty", f"robot state has no usable {field}")


def test_extend_refuses_to_grow_an_order_without_bound(client, published, monkeypatch):
    sent = _mission(client, "robot_big")
    _robot_state("v2", "robot_big", sent["order"], last_seq=2)
    monkeypatch.setattr(sent_orders_module, "MAX_NODES_PER_ORDER", 3)  # the mission already has 3 nodes

    _conflict(client, published, "robot_big", "order too long to extend; send a new mission")


def test_the_order_the_robot_reports_is_never_evicted(client, published, monkeypatch):
    monkeypatch.setattr(sent_orders_module, "MAX_ORDERS_PER_ROBOT", 2)
    first = _mission(client, "robot_ev")
    _robot_state("v2", "robot_ev", first["order"], last_seq=2)  # the robot runs the first order
    for _ in range(3):  # later missions it rejected: its state still names the first order
        client.post("/api/missions", json={**P1042, "robot_id": "robot_ev"})
    published.clear()

    assert _extend(client, "robot_ev").status_code == 202


def test_a_robot_cannot_make_us_publish_an_oversized_order_through_its_map_id(client, published):
    state = {"serialNumber": "robot_mp", "agvPosition": {"x": 1, "y": 2, "mapId": "\U0001f600" * 60000}}
    payload = json.dumps(state, ensure_ascii=False).encode()
    assert len(payload) < 256 * 1024  # small enough for the live hub to accept
    hub.handle_mqtt("uagv/v2/ActuNode/robot_mp/state", payload)

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_mp"})

    assert response.status_code == 202
    [(_, order)] = published
    assert len(order["nodes"]) == 2  # position ignored
    assert "has not reported a position yet" in response.json()["warning"]


@pytest.mark.parametrize("map_id", ["a b", "a/b", "", "x" * 65, "m\u00e9"])
@pytest.mark.parametrize("x", [1e7, float("inf")])
def test_unusable_reported_positions_are_ignored(client, published, map_id, x):
    _state_with_position("v2", "ActuNode", "robot_bp", x=x, map_id=map_id)
    _state_with_position("v3", "ActuNode", "robot_bp2", x=1, map_id=map_id)

    for robot in ("robot_bp", "robot_bp2"):
        client.post("/api/missions", json={**P1042, "robot_id": robot})

    assert all(len(order["nodes"]) == 2 for _, order in published)


def test_published_json_is_compact_and_not_escaped(client, monkeypatch):
    raw = []
    monkeypatch.setattr(mqtt_bridge, "publish", lambda topic, payload, qos=0: raw.append(payload))

    client.post("/api/missions", json={**P1042, "robot_id": "robot_cj"})
    client.post("/api/missions/robot_cj/cancel")

    assert all(", " not in payload and ": " not in payload for payload in raw)


def _too_large(topic, payload, qos=0):
    raise PayloadTooLarge("too big")


def test_oversized_messages_are_refused_with_422(client, published, monkeypatch):
    sent = _mission(client, "robot_tl")
    _robot_state("v2", "robot_tl", sent["order"], last_seq=2)
    monkeypatch.setattr(mqtt_bridge, "publish", _too_large)

    for response in (
        client.post("/api/missions", json={**P1042, "robot_id": "robot_tl"}),
        _extend(client, "robot_tl"),
        client.post("/api/missions/robot_tl/cancel"),
    ):
        assert response.status_code == 422
        assert response.json()["detail"] == "message too large for the broker"
