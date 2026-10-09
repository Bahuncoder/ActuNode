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
        mqtt_bridge, "publish",
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
