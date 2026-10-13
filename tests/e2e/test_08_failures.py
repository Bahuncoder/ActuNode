"""Week 6 failure injection on the real stack (D-42): low battery, blocked path, disconnect, invalid payload."""

import time

from conftest import CONNECTION_BROKEN, STATE_TOPIC, VDA, wait_for
from test_06_orders import distance, far_location, wait_idle

CONNECTION_TOPIC = f"uagv/v{VDA}/ActuNode/{{}}/connection"
BATTERY_LOW_LEVEL = "WARNING" if VDA == "2" else "URGENT"
BLOCKED_LEVEL = "WARNING" if VDA == "2" else "CRITICAL"


def inject(stack, robot_id: str, failure: str, action: str = "inject", **params):
    return stack.post("/failures", {"robot_id": robot_id, "failure": failure, "action": action, "params": params})


def state(stack, robot_id: str) -> dict:
    return stack.robots()[robot_id]["state"]


def battery(stack, robot_id: str) -> float:
    s = state(stack, robot_id)
    return s["batteryState"]["batteryCharge"] if VDA == "2" else s["powerSupply"]["stateOfCharge"]


def error_levels(stack, robot_id: str) -> dict[str, str]:
    return {e["errorType"]: e["errorLevel"] for e in state(stack, robot_id)["errors"]}


def connection(stack, robot_id: str) -> str | None:
    return stack.robots()[robot_id].get("connection")


def outside_charging(stack, robot_id: str) -> None:
    """Idle and outside the charging area (0-12 x 0-4 m), where a robot would charge."""
    wait_idle(stack, robot_id)
    x, y = stack.position(robot_id)
    if x <= 12 and y <= 4:
        stack.run_mission(robot_id, "RECEIVING_DOOR_2", timeout=60)


def test_low_battery_is_reported_and_clears(stack):
    robot_id = "robot_01"
    outside_charging(stack, robot_id)
    before = battery(stack, robot_id)

    inject(stack, robot_id, "LOW_BATTERY", level=12)
    wait_for(lambda: abs(battery(stack, robot_id) - 12) <= 1, 5, "battery about 12 %")
    wait_for(lambda: error_levels(stack, robot_id).get("batteryLow") == BATTERY_LOW_LEVEL, 5, "batteryLow reported")

    inject(stack, robot_id, "LOW_BATTERY", action="clear")
    wait_for(lambda: abs(battery(stack, robot_id) - before) <= 1, 5, f"battery back to about {before}")
    wait_for(lambda: "batteryLow" not in error_levels(stack, robot_id), 5, "batteryLow cleared")


def test_blocked_path_level_matches_the_version(stack):
    robot_id = "robot_02"
    wait_idle(stack, robot_id)
    destination = far_location(stack, robot_id, 8)
    order_id = stack.post(
        "/missions", {"vda_version": VDA, "robot_id": robot_id, "destination": destination}, expect=202
    ).json()["order_id"]
    wait_for(lambda: stack.status(robot_id) == "MOVING", 10, f"{robot_id} MOVING")
    time.sleep(1)

    inject(stack, robot_id, "BLOCKED_PATH")
    wait_for(lambda: error_levels(stack, robot_id).get("pathBlocked") == BLOCKED_LEVEL, 5, "pathBlocked level")

    inject(stack, robot_id, "BLOCKED_PATH", action="clear")

    def done() -> bool:
        s = state(stack, robot_id)
        return s["orderId"] == order_id and s["actunode"]["missionStatus"] == "COMPLETED"

    wait_for(done, 60, f"{robot_id} completed {order_id}")


def disconnect_cycle(stack, robot_id: str, mode: str, expected: str, duration: int = 3) -> None:
    with stack.watch(CONNECTION_TOPIC.format(robot_id)) as messages:
        mark = len(messages)
        inject(stack, robot_id, "DISCONNECT", duration_s=duration, mode=mode)

        def seen(value: str) -> bool:
            return any(p and p.get("connectionState") == value for _, _, p, _ in messages[mark:])

        wait_for(lambda: seen(expected), 5, f"{expected} on the connection topic")
        wait_for(lambda: connection(stack, robot_id) == expected, 5, f"backend shows {expected}")
        wait_for(lambda: seen("ONLINE"), duration + 10, "ONLINE again on the connection topic")
        wait_for(lambda: connection(stack, robot_id) == "ONLINE", 5, "backend shows ONLINE")


def test_disconnect_broken_publishes_the_last_will_and_reconnects(stack):
    robot_id = "robot_03"
    wait_idle(stack, robot_id)
    disconnect_cycle(stack, robot_id, "broken", CONNECTION_BROKEN)


def test_disconnect_offline_is_clean(stack):
    robot_id = "robot_03"
    wait_idle(stack, robot_id)
    disconnect_cycle(stack, robot_id, "offline", "OFFLINE")


def test_robot_keeps_its_order_while_disconnected(stack):
    robot_id = "robot_03"
    wait_idle(stack, robot_id)
    destination = far_location(stack, robot_id, 10, farthest=True)
    order_id = stack.post(
        "/missions", {"vda_version": VDA, "robot_id": robot_id, "destination": destination}, expect=202
    ).json()["order_id"]
    wait_for(lambda: stack.status(robot_id) == "MOVING", 10, f"{robot_id} MOVING")
    time.sleep(1)
    before = stack.position(robot_id)

    inject(stack, robot_id, "DISCONNECT", duration_s=5, mode="broken")
    wait_for(lambda: connection(stack, robot_id) == CONNECTION_BROKEN, 5, "robot disconnected")
    wait_for(lambda: connection(stack, robot_id) == "ONLINE", 15, "robot reconnected")
    stale = stack.robots()[robot_id]["lastStateAt"]  # the reconnect may precede the first fresh state
    wait_for(lambda: stack.robots()[robot_id]["lastStateAt"] != stale, 5, "fresh state after reconnect")
    assert state(stack, robot_id)["orderId"] == order_id
    assert distance(stack.position(robot_id), before) > 1, "robot did not keep driving while disconnected"

    def done() -> bool:
        s = state(stack, robot_id)
        return s["orderId"] == order_id and s["actunode"]["missionStatus"] == "COMPLETED"

    wait_for(done, 90, f"{robot_id} completed {order_id}")


def test_invalid_payload_is_flagged_by_the_validator(stack):
    robot_id = "robot_01"
    wait_idle(stack, robot_id)
    stack.post("/validation/reset", expect=200)
    kinds = ("not-json", "schema", "wrong-serial", "wrong-version")
    with stack.watch(STATE_TOPIC.format(robot_id)) as messages:
        for kind in kinds:
            assert inject(stack, robot_id, "INVALID_PAYLOAD", kind=kind, count=1).status_code == 202
            time.sleep(1.5)
        mark = len(messages)
        wait_for(lambda: len(messages) >= mark + 2, 5, "normal state messages afterwards")
    rules = {r["rule"] for r in stack.api.get("/validation").json()["byRule"]}
    assert {"invalid-json", "schema", "topic-mismatch", "version-mismatch"} <= rules, rules
    last = messages[-1][2]
    assert last and last["serialNumber"] == robot_id
    # Leave the counters clean for any later file.
    stack.post("/validation/reset", expect=200)


def test_failure_requests_are_validated(stack):
    robot_id = "robot_01"
    assert inject(stack, robot_id, "LOW_BATTERY", level=0).status_code == 422
    assert inject(stack, robot_id, "DISCONNECT", action="clear").status_code == 422
    assert inject(stack, robot_id, "LOW_BATTERY", bogus=1).status_code == 422
