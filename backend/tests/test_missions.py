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


def test_order_to_a_3_0_robot_uses_its_version_and_passes_the_official_3_0_schema(client, published):
    from pathlib import Path

    from app.validator import Validator

    fixture = json.loads((Path(__file__).parent / "fixtures" / "v3_state.json").read_text())
    _seen(fixture["topic"], fixture["payload"])

    response = client.post("/api/missions", json={**P1042, "robot_id": "robot_31"})

    assert response.status_code == 202
    [(topic, order)] = published
    assert topic == "uagv/v3/ActuNode/robot_31/order"
    assert order["version"] == "3.0.0"
    assert all("startNodeId" not in edge and "endNodeId" not in edge for edge in order["edges"])
    assert Validator().check(topic, order, valid_json=True) == []


def test_order_goes_to_the_robots_own_manufacturer_topic(client, published):
    _seen("uagv/v2/VendorX/amr_1/state", {"serialNumber": "amr_1", "manufacturer": "VendorX"})

    client.post("/api/missions", json={**P1042, "robot_id": "amr_1"})

    [(topic, order)] = published
    assert topic == "uagv/v2/VendorX/amr_1/order"
    assert order["manufacturer"] == "VendorX"
    assert order["version"] == "2.1.0"
    assert "startNodeId" in order["edges"][0]


def test_order_to_a_robot_never_seen_uses_the_configured_default(client, published):
    client.post("/api/missions", json={**P1042, "robot_id": "robot_unseen"})

    [(topic, order)] = published
    assert topic == "uagv/v2/ActuNode/robot_unseen/order"
    assert order["version"] == "2.1.0"
