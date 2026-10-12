import json
import threading
from collections import OrderedDict
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app import vda5050
from app.live import hub
from app.mqtt_state import mqtt_bridge
from app.proximity import state_position
from app.warehouse import LOCATIONS

router = APIRouter(prefix="/api")


ROBOT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
# Orders sent per robot key ("<major>/<manufacturer>/<serial>"): orderId -> the nodes sent (3.0 wants them
# resent unchanged in an update) and the last update id sent. Memory only, capped (least recently used
# dropped) so made-up serials cannot grow it without bound. What the robot is actually running comes from
# its own state, never from this memory. One lock covers every read-modify-write (D-35).
MAX_REMEMBERED_ORDERS = 1000
MAX_ORDERS_PER_ROBOT = 10
_last_orders: OrderedDict[str, OrderedDict[str, dict]] = OrderedDict()
_lock = threading.Lock()


class Address(BaseModel):
    # Optional explicit addressing (default: ACTUNODE_VDA_MAJOR_VERSION and ActuNode). Restricted so it
    # can never inject MQTT topic levels or wildcards.
    manufacturer: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$", examples=["ActuNode"])
    vda_version: Literal["2", "3"] | None = None


class MissionRequest(Address):
    # Restricted so a robot id can never inject MQTT topic levels or wildcards.
    robot_id: str = Field(pattern=ROBOT_ID_PATTERN, examples=["robot_01"])
    destination: str = Field(examples=["STORAGE_A17"])
    source: str | None = Field(default=None, examples=["RECEIVING_DOOR_2"])
    load_id: str | None = Field(default=None, max_length=64, examples=["P-1042"])


class ExtendRequest(Address):
    to_location: str = Field(examples=["CHARGING"])
    action: Literal["pick", "drop"] = "drop"


@router.get("/locations")
def list_locations() -> dict:
    return LOCATIONS


@router.post("/missions", status_code=202)
def send_mission(mission: MissionRequest) -> dict:
    for name in (mission.source, mission.destination):
        if name is not None and name not in LOCATIONS:
            raise HTTPException(422, f"Unknown location: {name}")

    _require_broker()

    order_id = f"order-{uuid4().hex[:8]}"
    major, manufacturer = _address(mission)
    stops = []
    # Start where the robot is (from its own state, D-28), so the first node is trivially reachable.
    position = _reported_position(mission.robot_id, major, manufacturer)
    if position:
        _, x, y, map_id = position
        stops.append({"nodeId": f"start-{order_id}", "x": x, "y": y, "mapId": map_id, "actions": []})
    if mission.source:
        stops.append(_stop(mission.source, vda5050.load_action("pick", f"{order_id}-pick", mission.load_id)))
    stops.append(
        _stop(
            mission.destination,
            vda5050.load_action("drop", f"{order_id}-drop", mission.load_id) if mission.source else None,
        )
    )

    order = vda5050.build_order(mission.robot_id, order_id, stops, major, manufacturer)
    order_topic = vda5050.topic(mission.robot_id, "order", major, manufacturer)
    # VDA 5050 section 6.2: order is published with QoS 0.
    with _lock:
        mqtt_bridge.publish(order_topic, json.dumps(order), qos=0)
        _remember(_key(mission.robot_id, major, manufacturer), order)

    result = {"order_id": order_id, "topic": order_topic, "order": order}
    warning = _identity_warning(mission.robot_id, major, manufacturer)
    if not position:
        no_position = (
            f"{mission.robot_id} has not reported a position yet; it may reject the order (start node out of range)"
        )
        warning = f"{warning}; {no_position}" if warning else no_position
    if warning:
        result["warning"] = warning
    return result


@router.post("/missions/{robot_id}/cancel", status_code=202)
def cancel_mission(robot_id: str = Path(pattern=ROBOT_ID_PATTERN), target: Address | None = None) -> dict:
    major, manufacturer = _address(target or Address())
    _require_broker()
    action_id = f"cancel-{uuid4().hex[:8]}"
    message = vda5050.cancel_order_message(robot_id, action_id, major, manufacturer)
    instant_topic = vda5050.topic(robot_id, "instantActions", major, manufacturer)
    mqtt_bridge.publish(instant_topic, json.dumps(message), qos=0)
    return {"actionId": action_id, "topic": instant_topic}


@router.post("/missions/{robot_id}/extend", status_code=202)
def extend_mission(request: ExtendRequest, robot_id: str = Path(pattern=ROBOT_ID_PATTERN)) -> dict:
    if request.to_location not in LOCATIONS:
        raise HTTPException(422, f"Unknown location: {request.to_location}")
    _require_broker()
    major, manufacturer = _address(request)
    key = _key(robot_id, major, manufacturer)
    order_topic = vda5050.topic(robot_id, "order", major, manufacturer)

    with _lock:  # from reading the robot's state to recording the update: two extends cannot both send N+1
        state = _reported_state(robot_id, key)
        if state is None:
            raise HTTPException(409, f"no state from {robot_id} yet; cannot tell what it is running")
        if (state.get("actunode") or {}).get("missionStatus") == "CANCELLED":
            raise HTTPException(409, "order was cancelled; send a new mission")
        order_id = state.get("orderId")
        sent = _last_orders.get(key, {}).get(order_id) if isinstance(order_id, str) and order_id else None
        if sent is None:
            raise HTTPException(409, f"{robot_id} is running an order ActuNode did not send")
        if state.get("orderUpdateId") != sent["last_sent_update_id"]:
            raise HTTPException(409, "previous update not confirmed by the robot yet; retry in a moment")
        stitch = sent["nodes"].get(_decision_sequence_id(state))
        if stitch is None:
            raise HTTPException(409, f"cannot find the node {robot_id} is at in the order ActuNode sent")

        update_id = sent["last_sent_update_id"] + 1
        action = vda5050.load_action(request.action, f"{order_id}-u{update_id}-{request.action}", None)
        update = vda5050.build_order_update(
            robot_id, order_id, update_id, stitch, _stop(request.to_location, action), major, manufacturer
        )
        mqtt_bridge.publish(order_topic, json.dumps(update), qos=0)
        _remember(key, update)

    result = {"orderId": order_id, "orderUpdateId": update_id, "topic": order_topic}
    warning = _identity_warning(robot_id, major, manufacturer)
    if warning:
        result["warning"] = warning
    return result


def _require_broker() -> None:
    if not mqtt_bridge.connected:
        raise HTTPException(503, "MQTT broker is not connected")


def _key(robot_id: str, major: str, manufacturer: str) -> str:
    return f"{major}/{manufacturer}/{robot_id}"


def _remember(key: str, order: dict) -> None:
    orders = _last_orders.setdefault(key, OrderedDict())
    entry = orders.setdefault(order["orderId"], {"nodes": {}, "last_sent_update_id": 0})
    entry["nodes"].update({n["sequenceId"]: n for n in order["nodes"]})
    entry["last_sent_update_id"] = order["orderUpdateId"]
    orders.move_to_end(order["orderId"])
    while len(orders) > MAX_ORDERS_PER_ROBOT:
        orders.popitem(last=False)
    _last_orders.move_to_end(key)
    while len(_last_orders) > MAX_REMEMBERED_ORDERS:
        _last_orders.popitem(last=False)


def _reported_state(robot_id: str, key: str) -> dict | None:
    """The robot's own last state, for exactly the identity the order is addressed to."""
    for robot in hub.robots_for(robot_id):
        if robot["key"] == key and isinstance(robot["state"], dict):
            return robot["state"]
    return None


def _decision_sequence_id(state: dict):
    """Where an update must attach: the last released node still ahead, else the node the robot is at."""
    nodes = state.get("nodeStates")
    nodes = nodes if isinstance(nodes, list) else []
    released = [n.get("sequenceId") for n in nodes if isinstance(n, dict) and n.get("released") is True]
    return released[-1] if released else state.get("lastNodeSequenceId")


def _reported_position(robot_id: str, major: str, manufacturer: str):
    """The robot's own last reported position, for exactly the identity the order is addressed to."""
    state = _reported_state(robot_id, _key(robot_id, major, manufacturer))
    return state_position(state) if state else None


def _address(mission: Address) -> tuple[str, str]:
    """Topic version and manufacturer to send the order to: exactly what the request names, otherwise
    the configured defaults. Never inferred from observed traffic: the broker is anonymous, so any
    client can publish as any robot (D-21). Authenticity needs broker authentication (issue 12)."""
    major = f"v{mission.vda_version}" if mission.vda_version else vda5050.MAJOR_VERSION
    return major, mission.manufacturer or vda5050.MANUFACTURER


def _identity_warning(robot_id: str, major: str, manufacturer: str) -> str | None:
    """Advice only: say so if the robot has been seen, but never under the identity the order uses."""
    seen = hub.robots_for(robot_id)
    if not seen or any(i["vdaMajor"] == major and i["manufacturer"] == manufacturer for i in seen):
        return None
    options = ", ".join(f"{i['manufacturer']} {i['vdaMajor']}" for i in seen)
    return (
        f"{robot_id} has not been seen as {manufacturer} {major} (seen as: {options}); "
        "set manufacturer and vda_version if the order should go elsewhere"
    )


def _stop(location: str, action: dict | None) -> dict:
    position = LOCATIONS[location]
    return {
        "nodeId": location,
        "x": position["x"],
        "y": position["y"],
        "actions": [action] if action else [],
    }
