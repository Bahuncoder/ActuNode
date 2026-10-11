"""Week 2-5 behaviour on the real stack: state publishing, missions, failure injection, validation."""

import time
from datetime import datetime

from conftest import ROBOTS, STATE_TOPIC, VDA, wait_for

CHARGING = (11.0, 2.2)


def test_stack_is_healthy(stack):
    health = stack.api.get("/health").json()

    assert health["status"] == "ok"
    assert health["mqtt"]["connected"] is True
    robots = stack.robots()
    for robot_id in ROBOTS:
        assert robots[robot_id]["connection"] == "ONLINE"
        assert robots[robot_id]["state"]["actunode"]["missionStatus"] == "IDLE"
        assert robots[robot_id]["vdaMajor"] == f"v{VDA}"


def test_idle_robot_publishes_state_every_second(stack):
    """Week 2 objective: 'Robot publishes status every second'."""
    with stack.watch(STATE_TOPIC.format("robot_03")) as messages:
        wait_for(lambda: len([m for m in messages if not m[3]]) >= 6, 10, "6 live state messages")

    live = [(arrived, payload) for arrived, _, payload, retained in messages if not retained][:6]
    arrival_gaps = [b[0] - a[0] for a, b in zip(live, live[1:], strict=False)]
    stamped = [datetime.fromisoformat(payload["timestamp"]) for _, payload in live]
    stamp_gaps = [(b - a).total_seconds() for a, b in zip(stamped, stamped[1:], strict=False)]
    assert all(0.8 <= gap <= 1.2 for gap in arrival_gaps), f"arrival intervals not ~1 s: {arrival_gaps}"
    assert all(0.9 <= gap <= 1.1 for gap in stamp_gaps), f"timestamp intervals not ~1 s: {stamp_gaps}"
    header_ids = [payload["headerId"] for _, payload in live]
    assert header_ids == list(range(header_ids[0], header_ids[0] + len(header_ids))), header_ids


def test_mission_runs_through_the_state_machine(stack):
    with stack.watch(STATE_TOPIC.format("robot_01")) as messages:
        stack.run_mission("robot_01", "CHARGING")

    statuses = []
    for _, _, payload, _ in messages:
        status = payload["actunode"]["missionStatus"]
        if not statuses or statuses[-1] != status:
            statuses.append(status)
    assert statuses[statuses.index("ACCEPTED") :] == ["ACCEPTED", "MOVING", "COMPLETED"]
    x, y = stack.position("robot_01")
    assert (round(x, 2), round(y, 2)) == CHARGING


def test_blocked_path_stops_the_robot_until_cleared(stack):
    stack.post("/missions", {"vda_version": VDA, "robot_id": "robot_02", "destination": "RECEIVING_DOOR_1"}, expect=202)
    wait_for(lambda: stack.status("robot_02") == "MOVING", 10, "robot_02 MOVING")
    time.sleep(2)

    stack.post("/failures", {"robot_id": "robot_02"}, expect=202)
    wait_for(lambda: stack.status("robot_02") == "BLOCKED", 5, "robot_02 BLOCKED")
    stopped_at = stack.position("robot_02")
    time.sleep(2.5)

    state = stack.robots()["robot_02"]["state"]
    assert stack.position("robot_02") == stopped_at, "blocked robot moved"
    assert state["driving"] is False
    assert [error["errorType"] for error in state["errors"]] == ["pathBlocked"]

    stack.post("/failures", {"robot_id": "robot_02", "action": "clear"}, expect=202)
    wait_for(lambda: stack.status("robot_02") == "COMPLETED", 40, "robot_02 COMPLETED after clear")
    assert stack.robots()["robot_02"]["state"]["errors"] == []


def test_failure_on_idle_robot_is_refused(stack):
    response = stack.post("/failures", {"robot_id": "robot_03"})

    assert response.status_code == 409
    assert "IDLE" in response.json()["detail"]


def test_all_traffic_so_far_passes_validation(stack):
    """No protocol issues before the resilience tests (restarts legitimately produce header-id warnings).
    Proximity warnings are expected: the simulator has no collision avoidance, and robots driving out of
    the parking grid pass close to parked neighbours (D-22)."""
    validation = stack.api.get("/validation").json()

    assert validation["checked"] > 0
    protocol_issues = [rule for rule in validation["byRule"] if rule["rule"] != "proximity"]
    assert protocol_issues == [], protocol_issues


def test_two_robots_at_the_same_spot_raise_a_near_collision_warning(stack):
    """ActuNode does not steer robots apart (that is the fleet manager's job, D-22); it reports when they
    get too close. robot_01 is parked at CHARGING after the mission test; send robot_02 there too."""
    stack.run_mission("robot_02", "CHARGING")

    pairs = wait_for(lambda: stack.api.get("/proximity").json(), 5, "an active near-miss pair")
    # Pairs name robots by key "<major>/<manufacturer>/<serial>" (issue 19).
    assert [f"v{VDA}/ActuNode/robot_01", f"v{VDA}/ActuNode/robot_02"] in [pair["robots"] for pair in pairs]
    rules = {rule["rule"]: rule for rule in stack.api.get("/validation").json()["byRule"]}
    assert rules["proximity"]["severity"] == "warning"
    assert "robot_0" in rules["proximity"]["last"]["message"]
