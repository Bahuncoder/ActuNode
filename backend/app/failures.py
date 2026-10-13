"""Failure injection: tell a simulated robot that something went wrong."""

import json
import logging
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app import vda5050
from app.live import hub
from app.mqtt_state import mqtt_bridge

log = logging.getLogger("actunode.failures")

router = APIRouter(prefix="/api")

# Mission statuses where a robot has a route that can be blocked.
ON_ROUTE = ("ACCEPTED", "MOVING")


class _Params(BaseModel):
    # strict: level true / "15" / 15.0 are not integers
    model_config = ConfigDict(extra="forbid", strict=True)


class NoParams(_Params):
    pass


class LowBatteryParams(_Params):
    level: int = Field(15, ge=1, le=99)


class DisconnectParams(_Params):
    duration_s: int = Field(10, ge=1, le=300)
    mode: Literal["broken", "offline"] = "broken"


class InvalidPayloadParams(_Params):
    kind: Literal["not-json", "schema", "wrong-serial", "wrong-version"] = "schema"
    count: int = Field(1, ge=1, le=10)


PARAMS = {
    "BLOCKED_PATH": NoParams,
    "LOW_BATTERY": LowBatteryParams,
    "DISCONNECT": DisconnectParams,
    "INVALID_PAYLOAD": InvalidPayloadParams,
}
# Failures that end by themselves cannot be cleared: why.
NO_CLEAR = {
    "DISCONNECT": "DISCONNECT ends by itself after duration_s",
    "INVALID_PAYLOAD": "INVALID_PAYLOAD is a one-off burst and ends by itself",
}


class FailureRequest(BaseModel):
    robot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$", examples=["robot_01"])
    failure: Literal["BLOCKED_PATH", "LOW_BATTERY", "DISCONNECT", "INVALID_PAYLOAD"] = "BLOCKED_PATH"
    action: Literal["inject", "clear"] = "inject"
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self):
        if self.action == "clear" and self.failure in NO_CLEAR:
            raise ValueError(f"{self.failure} cannot be cleared: {NO_CLEAR[self.failure]}")
        if self.action == "clear":
            # A clear undoes an injection; parameters would be silently ignored, so refuse them.
            if self.params:
                raise ValueError("clear takes no params")
            return self
        try:
            self.params = PARAMS[self.failure](**self.params).model_dump()
        except ValidationError as error:
            # Re-raise so the 422 locates the field under params: ["body", "params", "<field>"].
            raise ValidationError.from_exception_data(
                "FailureRequest",
                [
                    {"type": e["type"], "loc": ("params", *e["loc"]), "input": e["input"], "ctx": e.get("ctx", {})}
                    for e in error.errors()
                ],
            ) from None
        return self


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
    injected = extra.get("injectedFailures")
    if request.failure == "LOW_BATTERY" and request.action == "clear" and isinstance(injected, list):
        # Older simulators do not report the list; those clear as before.
        if "LOW_BATTERY" not in injected:
            raise HTTPException(409, f"{request.robot_id} has no injected LOW_BATTERY to clear")
    blocked = request.failure == "BLOCKED_PATH"
    if blocked and request.action == "inject" and status not in ON_ROUTE:
        raise HTTPException(409, f"{request.robot_id} is {status}; {request.failure} needs a robot on a route")
    if blocked and request.action == "clear" and status != "BLOCKED":
        raise HTTPException(409, f"{request.robot_id} is {status}, not BLOCKED")

    command = {
        "injectionId": f"inj-{uuid4().hex[:8]}",
        "timestamp": vda5050.utc_timestamp(),
        "robotId": request.robot_id,
        "failure": request.failure,
        "action": request.action,
        "params": request.params,
    }
    topic = control_topic(request.robot_id, "inject")
    mqtt_bridge.publish(topic, json.dumps(command), qos=1)

    entry = {**command, "topic": topic, "robotStatus": status}
    hub.add_failure(entry)
    log.warning("%s %s on %s (was %s)", request.failure, request.action, request.robot_id, status)
    return entry
