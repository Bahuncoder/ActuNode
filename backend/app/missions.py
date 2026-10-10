import json
from datetime import UTC, datetime, timedelta
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
    # Optional explicit addressing; needed when the serial number was seen under more than one identity.
    # Restricted so it can never inject MQTT topic levels or wildcards.
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

    return {"order_id": order_id, "topic": order_topic, "order": order}


# Identities seen this recently count as active (robots publish state every second). A one-off
# spoofed message stops affecting routing after this; a continuing conflict keeps missions refused.
IDENTITY_WINDOW = timedelta(seconds=10)


def _address(mission: MissionRequest) -> tuple[str, str]:
    """Topic version and manufacturer to send the order to. Never routes by "last seen" alone.

    Candidates are the robot's identities active in the last IDENTITY_WINDOW (or, if none is active,
    all it was ever seen with). Explicit fields narrow the candidates; both fields given address the
    robot explicitly. Zero or several remaining candidates are refused (409), never guessed. A robot
    never seen gets the configured defaults, overridden by any explicit field.
    """
    seen = (hub.robot(mission.robot_id) or {}).get("identities", [])
    now = datetime.now(UTC)
    active = [i for i in seen if now - datetime.fromisoformat(i["lastSeen"]) <= IDENTITY_WINDOW]
    candidates = active or seen
    major = f"v{mission.vda_version}" if mission.vda_version else None

    if mission.manufacturer and major:
        return major, mission.manufacturer
    if not candidates:
        return major or vda5050.MAJOR_VERSION, mission.manufacturer or vda5050.MANUFACTURER

    matching = [
        i
        for i in candidates
        if (major is None or i["vdaMajor"] == major) and mission.manufacturer in (None, i["manufacturer"])
    ]
    if len(matching) == 1:
        return matching[0]["vdaMajor"], matching[0]["manufacturer"]
    options = ", ".join(f"{i['manufacturer']} {i['vdaMajor']}" for i in candidates)
    reason = "none of them matches the request" if not matching else "specify manufacturer and vda_version"
    raise HTTPException(409, f"{mission.robot_id} has been seen as {options}; {reason}")


def _stop(location: str, action: dict | None) -> dict:
    position = LOCATIONS[location]
    return {
        "nodeId": location,
        "x": position["x"],
        "y": position["y"],
        "actions": [action] if action else [],
    }
