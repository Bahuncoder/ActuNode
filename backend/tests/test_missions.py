import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mqtt_state import mqtt_bridge

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
    from app.live import hub

    hub.handle_mqtt(topic, json.dumps(payload).encode())


def test_order_to_a_3_0_robot_uses_the_requested_version_and_passes_the_official_3_0_schema(client, published):
    from pathlib import Path

    from app.validator import Validator

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
    _seen("uagv/v2/ActuNode/robot_ok/state", {"serialNumber": "robot_ok"})

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_ok"})

    assert "warning" not in response.json()


def test_order_to_a_robot_never_seen_uses_the_configured_default(client, published):
    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_unseen"})

    [(topic, order)] = published
    assert topic == "uagv/v2/ActuNode/robot_unseen/order"
    assert order["version"] == "2.1.0"
    assert "warning" not in response.json()


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
    from app.live import hub

    _seen("uagv/v2/Other/robot_w/state", {"serialNumber": "robot_w"})
    for _ in range(2):
        response = client.post("/api/missions", json={**P1042, "robot_id": "robot_w", "vda_version": "3"})
        topic, order = published[-1]
        hub.handle_mqtt(topic, json.dumps(order).encode())  # the broker echoes the order back

        assert "Other v2" in response.json()["warning"]
