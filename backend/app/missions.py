import json
from typing import Literal
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
    # Optional explicit addressing (default: ACTUNODE_VDA_MAJOR_VERSION and ActuNode). Restricted so it
    # can never inject MQTT topic levels or wildcards.
    manufacturer: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$", examples=["ActuNode"])
    vda_version: Literal["2", "3"] | None = None


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

    major, manufacturer = _address(mission)
    order = vda5050.build_order(mission.robot_id, order_id, stops, major, manufacturer)
    order_topic = vda5050.topic(mission.robot_id, "order", major, manufacturer)
    # VDA 5050 section 6.2: order is published with QoS 0.
    mqtt_bridge.publish(order_topic, json.dumps(order), qos=0)

    result = {"order_id": order_id, "topic": order_topic, "order": order}
    warning = _identity_warning(mission.robot_id, major, manufacturer)
    if warning:
        result["warning"] = warning
    return result


def _address(mission: MissionRequest) -> tuple[str, str]:
    """Topic version and manufacturer to send the order to: exactly what the request names, otherwise
    the configured defaults. Never inferred from observed traffic: the broker is anonymous, so any
    client can publish as any robot (D-21). Authenticity needs broker authentication (issue 12)."""
    major = f"v{mission.vda_version}" if mission.vda_version else vda5050.MAJOR_VERSION
    return major, mission.manufacturer or vda5050.MANUFACTURER


def _identity_warning(robot_id: str, major: str, manufacturer: str) -> str | None:
    """Advice only: say so if the robot has been seen, but never under the identity the order uses."""
    seen = (hub.robot(robot_id) or {}).get("identities", [])
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
