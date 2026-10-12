"""Week 3 behaviour on the real stack (D-35): orders start at the robot, cancelOrder, order extension."""

import math
import time

import pytest
from conftest import ORDER_TOPIC, VDA, wait_for

IDLE = ("COMPLETED", "CANCELLED", "IDLE")
# Every rule that means a schema or state-machine violation. Header-id (restarts) and proximity are allowed.
FORBIDDEN_RULES = {
    "schema",
    "invalid-json",
    "payload-too-large",
    "non-finite-number",
    "too-deep",
    "validator-error",
    "topic-mismatch",
    "version-mismatch",
    "timestamp",
    "order-sequence",
    "mission-transition",
    "driving-consistency",
    "last-node-regression",
    "value-range",
}


@pytest.fixture(scope="module", autouse=True)
def fresh_validation(stack):
    """Count only this file's traffic: test_04 deliberately publishes a malformed state message."""
    stack.post("/validation/reset", expect=200)


def locations(stack) -> dict:
    return stack.api.get("/locations").json()


def distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def far_location(stack, robot_id: str, minimum: float, farthest: bool = False) -> str:
    """A location at least `minimum` m from where the robot is now (the farthest one if asked)."""
    here = stack.position(robot_id)
    ranked = sorted(locations(stack).items(), key=lambda item: distance(here, (item[1]["x"], item[1]["y"])))
    name, spot = (
        ranked[-1] if farthest else next(i for i in ranked if distance(here, (i[1]["x"], i[1]["y"])) >= minimum)
    )
    assert distance(here, (spot["x"], spot["y"])) >= minimum, f"no location {minimum} m from {here}"
    return name


def wait_idle(stack, robot_id: str) -> None:
    wait_for(lambda: stack.status(robot_id) in IDLE, 60, f"{robot_id} idle")


def instant_action_state(stack, robot_id: str, action_id: str) -> dict | None:
    state = stack.robots()[robot_id]["state"]
    states = state["actionStates"] if VDA == "2" else state["instantActionStates"]
    return next((a for a in states if a["actionId"] == action_id), None)


def test_order_starts_where_the_robot_is(stack):
    robot_id = "robot_03"
    wait_idle(stack, robot_id)
    here = stack.position(robot_id)
    destination = far_location(stack, robot_id, 5)

    with stack.watch(ORDER_TOPIC.format(robot_id)) as messages:
        order_id = stack.run_mission(robot_id, destination, timeout=60)

    orders = [payload for _, _, payload, retained in messages if payload and payload["orderId"] == order_id]
    assert orders, "no order seen on the topic"
    first = orders[0]["nodes"][0]
    assert first["sequenceId"] == 0
    assert distance((first["nodePosition"]["x"], first["nodePosition"]["y"]), here) <= 0.01, (first, here)


def test_cancel_stops_the_robot_mid_route(stack):
    robot_id = "robot_02"
    wait_idle(stack, robot_id)
    start = stack.position(robot_id)
    destination = far_location(stack, robot_id, 15)
    stack.post("/missions", {"vda_version": VDA, "robot_id": robot_id, "destination": destination}, expect=202)
    wait_for(lambda: stack.status(robot_id) == "MOVING", 10, f"{robot_id} MOVING")
    wait_for(lambda: distance(stack.position(robot_id), start) >= 1, 10, f"{robot_id} moved 1 m")
    order_id = stack.robots()[robot_id]["state"]["orderId"]

    response = stack.post(f"/missions/{robot_id}/cancel", {"vda_version": VDA}, expect=202)
    action_id = response.json()["actionId"]

    wait_for(lambda: stack.status(robot_id) == "CANCELLED", 3, f"{robot_id} CANCELLED")
    state = stack.robots()[robot_id]["state"]
    assert state["nodeStates"] == [] and state["edgeStates"] == []
    assert state["driving"] is False
    assert state["orderId"] == order_id
    stopped_at = stack.position(robot_id)
    wait_for(
        lambda: (instant_action_state(stack, robot_id, action_id) or {}).get("actionStatus") == "FINISHED",
        3,
        "cancel FINISHED",
    )
    time.sleep(2)
    assert distance(stack.position(robot_id), stopped_at) <= 0.05, "cancelled robot kept moving"

    stack.run_mission(robot_id, far_location(stack, robot_id, 5), timeout=60)


def test_cancel_without_an_order_is_refused_by_the_robot(stack):
    robot_id = "robot_01"
    wait_idle(stack, robot_id)
    if stack.status(robot_id) == "IDLE":  # not reached after the earlier tests, but never assume
        stack.run_mission(robot_id, far_location(stack, robot_id, 5), timeout=60)

    action_id = stack.post(f"/missions/{robot_id}/cancel", {"vda_version": VDA}, expect=202).json()["actionId"]

    wait_for(
        lambda: (instant_action_state(stack, robot_id, action_id) or {}).get("actionStatus") == "FAILED",
        5,
        "cancel FAILED",
    )
    error_type = "noOrderToCancel" if VDA == "2" else "NO_ORDER_TO_CANCEL"
    errors = stack.robots()[robot_id]["state"]["errors"]
    matching = [
        e
        for e in errors
        if e["errorType"] == error_type
        and {"referenceKey": "actionId", "referenceValue": action_id} in e.get("errorReferences", [])
    ]
    assert matching, errors


def test_extend_continues_the_order_to_a_new_destination(stack):
    robot_id = "robot_01"
    wait_idle(stack, robot_id)
    first = far_location(stack, robot_id, 15)
    order_id = stack.post(
        "/missions", {"vda_version": VDA, "robot_id": robot_id, "destination": first}, expect=202
    ).json()["order_id"]
    wait_for(lambda: stack.status(robot_id) == "MOVING", 10, f"{robot_id} MOVING")
    second = next(name for name in locations(stack) if name != first and name != "CHARGING")

    response = stack.post(
        f"/missions/{robot_id}/extend", {"vda_version": VDA, "to_location": second}, expect=202
    ).json()
    assert response["orderUpdateId"] == 1
    assert response["orderId"] == order_id

    def done() -> bool:
        state = stack.robots()[robot_id]["state"]
        return state["orderUpdateId"] == 1 and state["actunode"]["missionStatus"] == "COMPLETED"

    wait_for(done, 90, f"{robot_id} completed the extended order")
    spot = locations(stack)[second]
    assert distance(stack.position(robot_id), (spot["x"], spot["y"])) <= 0.05
    assert stack.robots()[robot_id]["state"]["orderId"] == order_id


def test_week3_traffic_has_no_protocol_errors(stack):
    validation = stack.api.get("/validation").json()

    assert validation["checked"] > 0
    violations = [rule for rule in validation["byRule"] if rule["rule"] in FORBIDDEN_RULES]
    assert violations == [], violations
