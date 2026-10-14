"""An outside master control (fleet manager) drives ActuNode's simulated robots with its own login (D-47).

Runs last: adding a login restarts the broker, as it does for a user following the README.
"""

import json
import time
from datetime import UTC, datetime

import pytest
from conftest import HOST, VDA, wait_for
from test_06_orders import far_location, wait_idle

VERSION = "2.1.0" if VDA == "2" else "3.0.0"
ROBOT = "robot_03"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@pytest.fixture(scope="module")
def master(stack):
    out = stack.compose("run", "--rm", "--no-deps", "mqtt-init", "add-master", "e2e_fleet")
    password = out.split("password=")[1].split()[0]
    assert "it commands: ActuNode" in out
    stack.compose("up", "-d", "--force-recreate", "mqtt-init", "mosquitto")
    wait_for(lambda: stack.api.get("/health").json()["mqtt"]["connected"], 60, "backend back on the broker")
    wait_for(stack.all_online, 60, "robots back online")
    client = stack.mqtt_client("master@e2e_fleet", password)
    client.connect(HOST, stack.mqtt_port)
    client.loop_start()
    yield client
    client.loop_stop()
    client.disconnect()


def headers(serial: str, header_id: int) -> dict:
    return {
        "headerId": header_id,
        "timestamp": now(),
        "version": VERSION,
        "manufacturer": "ActuNode",
        "serialNumber": serial,
    }


def order_to(stack, serial: str, order_id: str, destination: str) -> dict:
    """An order as a fleet manager builds it: from where the robot reports it is, to a named location."""
    state = stack.robots()[serial]["state"]
    here = state.get("agvPosition") or state["mobileRobotPosition"]
    target = stack.api.get("/locations").json()[destination]
    node = {"released": True, "actions": []}
    return {
        **headers(serial, 1),
        "orderId": order_id,
        "orderUpdateId": 0,
        "nodes": [
            {
                **node,
                "nodeId": "here",
                "sequenceId": 0,
                "nodePosition": {"x": here["x"], "y": here["y"], "mapId": here["mapId"]},
            },
            {
                **node,
                "nodeId": destination,
                "sequenceId": 2,
                "nodePosition": {"x": target["x"], "y": target["y"], "mapId": here["mapId"]},
            },
        ],
        "edges": [
            {
                "edgeId": f"here->{destination}",
                "sequenceId": 1,
                "released": True,
                "startNodeId": "here",
                "endNodeId": destination,
                "actions": [],
            }
        ],
    }


def issues_on(stack, topic: str, key: str, value: str) -> list | None:
    for message in reversed(stack.api.get("/messages").json()):
        if message["topic"] == topic and isinstance(message["payload"], dict) and message["payload"].get(key) == value:
            return message["issues"]
    return None


def test_an_outside_fleet_manager_sends_an_order_and_cancels_it(stack, master):
    wait_idle(stack, ROBOT)
    destination = far_location(stack, ROBOT, 15)
    order_topic = f"uagv/v{VDA}/ActuNode/{ROBOT}/order"
    master.publish(order_topic, json.dumps(order_to(stack, ROBOT, "fm-e2e-1", destination)), qos=1)

    def running() -> bool:
        state = stack.robots()[ROBOT]["state"]
        return state["orderId"] == "fm-e2e-1" and state["actunode"]["missionStatus"] == "MOVING"

    wait_for(running, 10, f"{ROBOT} runs the fleet manager's order")
    # Inspected and valid. Earlier tests sent this robot orders through ActuNode's own backend, so the outside
    # sender's headerId restarting at 1 on the same topic is rightly a header-id warning (one master per robot).
    issues = issues_on(stack, order_topic, "orderId", "fm-e2e-1")
    assert issues is not None
    assert [i for i in issues if i["rule"] != "header-id"] == [] and all(i["severity"] == "warning" for i in issues)

    cancel = {
        **headers(ROBOT, 2),
        "actions": [
            {"actionId": "fm-e2e-cancel", "actionType": "cancelOrder", "blockingType": "NONE", "actionParameters": []}
        ],
    }
    if VDA == "3":
        cancel["actions"][0].pop("actionParameters")
    master.publish(f"uagv/v{VDA}/ActuNode/{ROBOT}/instantActions", json.dumps(cancel), qos=1)
    wait_for(lambda: stack.status(ROBOT) == "CANCELLED", 10, f"{ROBOT} cancelled by the fleet manager")


def test_a_fleet_manager_login_is_scoped(stack, master):
    master.publish(f"uagv/v{VDA}/Acme/amr_9/order", json.dumps({"orderId": "fm-e2e-rogue"}))
    master.publish(f"uagv/v{VDA}/ActuNode/robot_01/state", json.dumps({"serialNumber": "robot_01", "spoof": True}))
    master.publish("actunode/v1/sim/robot_01/inject", json.dumps({"failure": "LOW_BATTERY", "action": "inject"}))
    time.sleep(2)
    topics = {m["topic"]: m["payload"] for m in stack.api.get("/messages").json()}
    assert f"uagv/v{VDA}/Acme/amr_9/order" not in topics  # another manufacturer's robots
    assert {"serialNumber": "robot_01", "spoof": True} not in topics.values()  # cannot speak as a robot
    errors = {e["errorType"] for e in stack.robots()["robot_01"]["state"]["errors"]}
    assert "batteryLow" not in errors  # cannot inject failures
