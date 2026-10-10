import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import vda5050
from app.live import hub
from app.mqtt_state import mqtt_bridge
from app.warehouse import LOCATIONS

router = APIRouter(prefix="/api")


class MissionRequest(BaseModel):
    # Restricted so a robot id can never inject MQTT topic levels or wildcards.
    robot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$", examples=["robot_01"])
    destination: str = Field(examples=["STORAGE_A17"])
    source: str | None = Field(default=None, examples=["RECEIVING_DOOR_2"])
    load_id: str | None = Field(default=None, max_length=64, examples=["P-1042"])


@router.get("/locations")
def list_locations() -> dict:
    return LOCATIONS


@router.post("/missions", status_code=202)
def send_mission(mission: MissionRequest) -> dict:
    for name in (mission.source, mission.destination):
        if name is not None and name not in LOCATIONS:
            raise HTTPException(422, f"Unknown location: {name}")

    if not mqtt_bridge.connected:
        raise HTTPException(503, "MQTT broker is not connected")

    order_id = f"order-{uuid4().hex[:8]}"
    stops = []
    if mission.source:
        stops.append(_stop(mission.source, vda5050.load_action("pick", f"{order_id}-pick", mission.load_id)))
    stops.append(
        _stop(
            mission.destination,
            vda5050.load_action("drop", f"{order_id}-drop", mission.load_id) if mission.source else None,
        )
    )

    # Address the robot the way it speaks: its own topic version and manufacturer, as last seen.
    # A robot not seen yet gets the configured defaults.
    seen = hub.robot(mission.robot_id) or {}
    major = seen.get("vdaMajor") or vda5050.MAJOR_VERSION
    manufacturer = seen.get("manufacturer") or vda5050.MANUFACTURER
    order = vda5050.build_order(mission.robot_id, order_id, stops, major, manufacturer)
    order_topic = vda5050.topic(mission.robot_id, "order", major, manufacturer)
    # VDA 5050 section 6.2: order is published with QoS 0.
    mqtt_bridge.publish(order_topic, json.dumps(order), qos=0)

    return {"order_id": order_id, "topic": order_topic, "order": order}


def _stop(location: str, action: dict | None) -> dict:
    position = LOCATIONS[location]
    return {
        "nodeId": location,
        "x": position["x"],
        "y": position["y"],
        "actions": [action] if action else [],
    }
