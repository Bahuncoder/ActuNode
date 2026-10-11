"""Failure injection: tell a simulated robot that something went wrong."""

import json
import logging
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import vda5050
from app.live import hub
from app.mqtt_state import mqtt_bridge

log = logging.getLogger("actunode.failures")

router = APIRouter(prefix="/api")

# Mission statuses where a robot has a route that can be blocked.
ON_ROUTE = ("ACCEPTED", "MOVING")


class FailureRequest(BaseModel):
    robot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$", examples=["robot_01"])
    failure: Literal["BLOCKED_PATH"] = "BLOCKED_PATH"
    action: Literal["inject", "clear"] = "inject"


def control_topic(serial_number: str, name: str) -> str:
    return f"actunode/v1/sim/{serial_number}/{name}"


@router.get("/failures")
def failure_log() -> list[dict]:
    return hub.snapshot()["failures"]


@router.post("/failures", status_code=202)
def inject_failure(request: FailureRequest) -> dict:
    if not mqtt_bridge.connected:
        raise HTTPException(503, "MQTT broker is not connected")

    heard = hub.robots_for(request.robot_id)
    if not heard:
        raise HTTPException(404, f"Unknown robot: {request.robot_id}")
    # The inject topic only reaches ActuNode's simulated robots; a same-serial robot of another
    # manufacturer must neither block nor receive it. Most recently heard first.
    robot = next((r for r in heard if r["manufacturer"] == vda5050.MANUFACTURER), None)
    if robot is None:
        raise HTTPException(409, f"{request.robot_id} is not a simulated ActuNode robot; failures reach only those")
    if robot["connection"] != "ONLINE":
        raise HTTPException(409, f"{request.robot_id} is {robot['connection'] or 'not connected'}")

    state = robot["state"] if isinstance(robot["state"], dict) else {}
    extra = state.get("actunode") if isinstance(state.get("actunode"), dict) else {}
    status = extra.get("missionStatus", "UNKNOWN")
    if request.action == "inject" and status not in ON_ROUTE:
        raise HTTPException(409, f"{request.robot_id} is {status}; {request.failure} needs a robot on a route")
    if request.action == "clear" and status != "BLOCKED":
        raise HTTPException(409, f"{request.robot_id} is {status}, not BLOCKED")

    command = {
        "injectionId": f"inj-{uuid4().hex[:8]}",
        "timestamp": vda5050.utc_timestamp(),
        "robotId": request.robot_id,
        "failure": request.failure,
        "action": request.action,
    }
    topic = control_topic(request.robot_id, "inject")
    mqtt_bridge.publish(topic, json.dumps(command), qos=1)

    entry = {**command, "topic": topic, "robotStatus": status}
    hub.add_failure(entry)
    log.warning("%s %s on %s (was %s)", request.failure, request.action, request.robot_id, status)
    return entry
