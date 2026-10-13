"""Instant actions per D-35: cancelOrder, pause, requests, clearInstantActions, unknown actions, states and caps."""

import pytest

from simulator.robot import CANCELLED, COMPLETED, FAILED, MAX_INSTANT_ACTION_STATES, MOVING, Robot
from simulator.tests.helpers import (
    BOTH,
    act,
    driving_robot,
    horizon_order,
    instants,
    make_order,
    official,
    run,
    status,
    types,
)


@BOTH
def test_action_states_live_where_the_version_puts_them(major):
    robot = Robot("robot_01", vda_major=major)
    assert act(robot, "stateRequest")
    state = robot.state_message()

    assert [a["actionId"] for a in state["instantActionStates" if major == "v3" else "actionStates"]] == ["i-1"]
    if major == "v3":
        assert state["actionStates"] == []


@BOTH
def test_cancel_order_stops_the_robot_and_frees_it(major):
    robot = driving_robot(major)
    assert robot.state_message()["driving"] is True

    act(robot, "cancelOrder")
    state = robot.state_message()

    assert state["driving"] is False and state["velocity"]["vx"] == 0
    assert state["nodeStates"] == [] and state["edgeStates"] == []
    assert (state["orderId"], state["orderUpdateId"], state["lastNodeId"]) == ("o-1", 0, "N0")
    assert robot.mission_status == CANCELLED and robot.cancelled is True
    assert status(robot, "i-1") == "FINISHED"
    assert next(a for a in robot.action_states if a["actionId"] == "a-drop")["actionStatus"] == "FAILED"
    robot.update(0.1)
    assert robot.state_message()["driving"] is False
    assert robot.accept_order(make_order(order_id="o-2", points=((robot.x, 0), (robot.x + 1, 0))))
    assert robot.cancelled is False


@BOTH
def test_update_after_cancel_is_rejected(major):
    order = horizon_order(released=2)
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(order)
    act(robot, "cancelOrder")

    update = horizon_order(update_id=1)
    assert not robot.accept_order(update)
    assert types(robot) == ["ORDER_UPDATE_FOLLOWING_CANCEL" if major == "v3" else "orderUpdateError"]


@BOTH
def test_cancel_order_without_order_fails_with_warning(major):
    robot = Robot("robot_01", vda_major=major)
    act(robot, "cancelOrder")

    error = robot.errors[0]
    assert status(robot, "i-1") == "FAILED"
    assert error["errorType"] == ("NO_ORDER_TO_CANCEL" if major == "v3" else "noOrderToCancel")
    assert error["errorLevel"] == "WARNING"
    assert error["errorReferences"] == [{"referenceKey": "actionId", "referenceValue": "i-1"}]
    assert robot.mission_status != CANCELLED
    # Reported until a new order is accepted.
    assert robot.accept_order(make_order())
    assert robot.errors == []


@BOTH
def test_cancel_order_after_completion_fails(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(points=((0, 0), (1, 0))))
    run(robot, 5)
    assert robot.mission_status == COMPLETED

    act(robot, "cancelOrder")

    assert status(robot, "i-1") == "FAILED"


def test_3_0_cancel_order_with_matching_order_id_cancels():
    robot = driving_robot("v3")
    act(robot, "cancelOrder", orderId="o-1")
    assert robot.mission_status == CANCELLED and status(robot, "i-1") == "FINISHED"


def test_3_0_cancel_order_with_other_order_id_fails_and_keeps_driving():
    robot = driving_robot("v3")
    act(robot, "cancelOrder", orderId="other")

    assert status(robot, "i-1") == "FAILED" and types(robot) == ["NO_ORDER_TO_CANCEL"]
    assert robot.mission_status == MOVING


@BOTH
def test_pause_stops_driving_and_resume_continues(major):
    robot = driving_robot(major)
    act(robot, "startPause", "p1")
    x = robot.x
    run(robot, 2)
    state = robot.state_message()

    assert state["paused"] is True and state["driving"] is False and state["velocity"]["vx"] == 0
    assert robot.x == x and robot.mission_status == MOVING
    assert status(robot, "p1") == "FINISHED"

    act(robot, "stopPause", "p2")
    run(robot, 1)
    assert robot.state_message()["paused"] is False and robot.x > x
    assert status(robot, "p2") == "FINISHED"


@BOTH
def test_pause_is_idempotent(major):
    robot = Robot("robot_01", vda_major=major)
    act(robot, "stopPause", "a")  # not paused
    act(robot, "startPause", "b")
    act(robot, "startPause", "c")  # already paused

    assert [status(robot, i) for i in "abc"] == ["FINISHED"] * 3 and robot.paused


@BOTH
def test_state_request_changes_event_signature(major):
    robot = Robot("robot_01", vda_major=major)
    before = robot.event_signature()
    act(robot, "stateRequest")

    assert robot.event_signature() != before and status(robot, "i-1") == "FINISHED"


@BOTH
def test_pause_changes_event_signature(major):
    robot = Robot("robot_01", vda_major=major)
    robot.paused = True
    assert robot.event_signature() != Robot("robot_01", vda_major=major).event_signature()


@BOTH
def test_factsheet_request_sets_flag(major):
    robot = Robot("robot_01", vda_major=major)
    act(robot, "factsheetRequest")

    assert robot.factsheet_requested is True and status(robot, "i-1") == "FINISHED"


def test_3_0_clear_instant_actions_keeps_only_itself():
    robot = Robot("robot_01", vda_major="v3")
    act(robot, "stateRequest", "a")
    act(robot, "stateRequest", "b")
    act(robot, "clearInstantActions", "c")

    assert [a["actionId"] for a in robot.instant_action_states] == ["c"]
    assert status(robot, "c") == "FINISHED"


def test_2_1_has_no_clear_instant_actions():
    robot = Robot("robot_01")
    act(robot, "clearInstantActions")

    assert status(robot, "i-1") == "FAILED" and robot.errors == []


def test_3_0_unknown_action_fails_with_error_until_next_instant_action():
    robot = Robot("robot_01", vda_major="v3")
    act(robot, "dance")

    error = robot.errors[0]
    assert status(robot, "i-1") == "FAILED"
    assert (error["errorType"], error["errorLevel"]) == ("INVALID_INSTANT_ACTION", "WARNING")
    assert error["errorReferences"] == [{"referenceKey": "actionId", "referenceValue": "i-1"}]
    robot.accept_order(make_order())
    assert types(robot) == ["INVALID_INSTANT_ACTION"]  # orders do not clear it
    act(robot, "stateRequest", "i-2")
    assert robot.errors == []


def test_2_1_unknown_action_fails_with_description_only():
    robot = Robot("robot_01")
    act(robot, "dance")

    published = robot.state_message()["actionStates"][0]
    assert published["actionStatus"] == "FAILED"
    assert "dance" in published["resultDescription"]
    assert robot.errors == []


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        b'{"actions": "x"}',
        b'{"instantActions": []}',
        b'{"actions": [1]}',
        b'{"actions": [{"actionType": "startPause"}]}',
        b'{"actions": [{"actionType": 5, "actionId": "x"}]}',
    ],
)
@BOTH
def test_malformed_message_is_ignored(major, payload):
    robot = Robot("robot_01", vda_major=major)

    assert robot.handle_instant_actions_payload(payload) is False
    assert robot.action_states == [] and robot.instant_action_states == [] and robot.errors == []


@BOTH
def test_instant_action_states_are_capped_dropping_the_oldest(major):
    robot = Robot("robot_01", vda_major=major)
    for i in range(MAX_INSTANT_ACTION_STATES + 5):
        act(robot, "stateRequest", f"s-{i}")

    ids = [a["actionId"] for a in instants(robot)]
    assert len(ids) == MAX_INSTANT_ACTION_STATES and ids[0] == "s-5" and ids[-1] == f"s-{MAX_INSTANT_ACTION_STATES + 4}"


def test_new_order_clears_2_1_instant_states_but_not_3_0():
    for major, expect in (("v2", []), ("v3", ["s"])):
        robot = Robot("robot_01", vda_major=major)
        act(robot, "stateRequest", "s")
        robot.accept_order(make_order(order_id="n", points=((0, 0), (3, 0))))

        assert [a["actionId"] for a in instants(robot) if a["actionId"] == "s"] == expect


def test_new_order_keeps_running_2_1_instant_action():
    robot = Robot("robot_01")
    act(robot, "stateRequest", "s")
    robot.instant_action_states[0]["actionStatus"] = "RUNNING"  # nothing in the simulator runs long; force it
    robot.accept_order(make_order())

    assert [a["actionId"] for a in robot.state_message()["actionStates"] if a["actionId"] == "s"] == ["s"]


@BOTH
def test_battery_empty_order_is_kept_until_cancelled(major):
    robot = Robot("robot_01", x=10, y=2, vda_major=major)
    robot.battery = 0.2
    robot.accept_order(make_order(order_id="order-9", points=((10, 2), (100, 2))))
    while robot.mission_status != FAILED:
        robot.update(0.1)
    robot.update(1.0)  # in the charging area: charges and clears batteryEmpty
    assert types(robot) == ["batteryLow"] and robot.mission_status == FAILED and robot.node_states  # 1 % charged

    assert not robot.accept_order(make_order(order_id="order-10", points=((robot.x, robot.y), (11, 2))))
    assert types(robot)[-1] == ("OTHER_ORDER_ACTIVE" if major == "v3" else "orderError")

    act(robot, "cancelOrder")
    assert robot.mission_status == CANCELLED
    assert robot.accept_order(make_order(order_id="order-10", points=((robot.x, robot.y), (11, 2))))


@BOTH
def test_factsheet_lists_instant_actions(major):
    factsheet = Robot("robot_01", vda_major=major).factsheet_message()
    actions = factsheet["protocolFeatures"]["mobileRobotActions" if major == "v3" else "agvActions"]
    instant = {a["actionType"] for a in actions if a["actionScopes"] == ["INSTANT"]}

    expected = {"cancelOrder", "startPause", "stopPause", "stateRequest", "factsheetRequest"}
    assert instant == expected | ({"clearInstantActions"} if major == "v3" else set())
    assert not list(official(major, "factsheet").iter_errors(factsheet))


@BOTH
def test_instant_action_states_pass_the_official_schema(major):
    robot = driving_robot(major)
    states = []
    act(robot, "startPause", "p")
    states.append(robot.state_message())
    act(robot, "dance", "d")
    states.append(robot.state_message())
    act(robot, "cancelOrder", "c")
    states.append(robot.state_message())
    act(robot, "cancelOrder", "c2")  # nothing left to cancel
    states.append(robot.state_message())

    failures = [e.message for state in states for e in official(major, "state").iter_errors(state)]
    assert not failures
    assert states[1]["paused"] is True and states[-1]["errors"]
