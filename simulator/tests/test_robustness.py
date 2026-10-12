"""Review fixes: actionParameters validation, atomic orders, empty-battery updates, bounded state, duplicates."""

import copy
import json

import pytest

from simulator.__main__ import step
from simulator.robot import FAILED, MAX_INSTANT_ACTION_STATES, MOVING, Robot
from simulator.tests.test_instant_actions import act, driving_robot, instants
from simulator.tests.test_orders import BOTH, horizon_order, run, types, update_from
from simulator.tests.test_robot import make_order

BAD_PARAMETERS = [5, None, "x", [1], [{"value": 1}], [{"key": 1, "value": 1}]]


def send(robot, actions):
    return robot.handle_instant_actions_payload(json.dumps({"actions": actions}).encode())


def snapshot(robot):
    return copy.deepcopy(robot.__dict__)


# --- H1 -----------------------------------------------------------------


@BOTH
@pytest.mark.parametrize("bad", BAD_PARAMETERS)
@pytest.mark.parametrize("where", ["node", "edge"])
def test_bad_action_parameters_reject_the_order_untouched(major, bad, where):
    robot = Robot("robot_01", vda_major=major)
    before = snapshot(robot)
    order = make_order()
    item = order["nodes" if where == "node" else "edges"][-1 if where == "node" else 0]
    item["actions"] = [{"actionId": "x", "actionType": "pick", "blockingType": "HARD", "actionParameters": bad}]

    assert robot.accept_order(order) is False

    assert types(robot) == ["validationError" if major == "v2" else "VALIDATION_FAILURE"]
    assert "actionParameters" in json.dumps(robot.errors[0]["errorReferences"])
    errors = robot.errors
    robot.errors = []
    assert robot.__dict__ == {**before, "errors": []} and errors


@BOTH
def test_bad_action_parameters_reject_an_update_untouched(major):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    robot.accept_order(order)
    update = update_from(order, 1, 3)
    update["nodes"][-1]["actions"] = [
        {"actionId": "u", "actionType": "pick", "blockingType": "HARD", "actionParameters": 5}
    ]
    before = snapshot(robot)

    assert robot.accept_order(update) is False

    robot.errors = []
    assert robot.__dict__ == {**before, "errors": []}


@BOTH
@pytest.mark.parametrize("action_type", ["cancelOrder", "stateRequest", "startPause", "nonsense"])
@pytest.mark.parametrize("bad", [5, None, [1], [{"key": 2}]])
def test_instant_action_with_bad_parameters_fails_without_raising(major, action_type, bad):
    robot = driving_robot(major)
    action = {"actionType": action_type, "actionId": "i-1", "blockingType": "HARD", "actionParameters": bad}

    assert send(robot, [action]) is True

    assert next(a for a in instants(robot) if a["actionId"] == "i-1")["actionStatus"] == "FAILED"
    assert robot.mission_status == MOVING and not robot.cancelled and not robot.paused
    if major == "v3":
        assert "INVALID_INSTANT_ACTION" in types(robot)


@BOTH
def test_valid_action_parameters_are_still_accepted(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["nodes"][0]["actions"][0]["actionParameters"] = [{"key": "loadId", "value": "L1"}, {"key": "n", "value": 3}]
    assert robot.accept_order(order) is True


@BOTH
@pytest.mark.parametrize("update", [False, True])
def test_order_application_is_atomic(major, update, monkeypatch):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    if update:
        robot.accept_order(order)
        order = update_from(order, 1, 3)
    before = snapshot(robot)
    real, calls = robot._add_actions, []

    def failing(actions):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(actions)

    monkeypatch.setattr(robot, "_add_actions", failing)
    with pytest.raises(RuntimeError):
        robot.accept_order(order)

    assert len(calls) == 2
    assert robot.__dict__ == {**before, "_add_actions": failing}


# --- M1 -----------------------------------------------------------------


def failed_at_decision_point(major):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order(released=2)
    robot.battery = 0.3
    robot.accept_order(order)
    run(robot, 5)
    assert robot.mission_status == FAILED
    return robot, order


@BOTH
def test_update_accepted_after_recharge_resumes_driving(major):
    robot, order = failed_at_decision_point(major)
    robot.battery = 50.0

    assert robot.accept_order(update_from(order, 1, 3)) is True
    assert robot.mission_status == MOVING
    run(robot, 1)
    assert robot.state_message()["driving"] is True


@BOTH
def test_update_with_empty_battery_is_rejected(major):
    robot, order = failed_at_decision_point(major)
    robot.battery = 0.0

    assert robot.accept_order(update_from(order, 1, 3)) is False
    assert types(robot) == ["orderUpdateError" if major == "v2" else "MOBILE_ROBOT_NOT_AVAILABLE"]
    assert robot.errors[0]["errorLevel"] == "WARNING" and robot.mission_status == FAILED
    assert robot.order_update_id == 0


# --- M3 / M4 ------------------------------------------------------------


def test_unknown_instant_actions_flood_stays_small():
    robot = Robot("robot_01", vda_major="v3")
    flood = [{"actionType": "nope", "actionId": f"flood-{i:05d}", "blockingType": "HARD"} for i in range(5000)]

    assert send(robot, flood) is True

    assert len(json.dumps(robot.state_message())) < 64 * 1024
    errors = [e for e in robot.errors if e["errorType"] == "INVALID_INSTANT_ACTION"]
    assert len(errors) == 1 and len(errors[0]["errorReferences"]) <= 50
    assert len(robot.instant_action_states) <= MAX_INSTANT_ACTION_STATES


def test_one_invalid_instant_error_lists_every_offender_of_the_message():
    robot = Robot("robot_01", vda_major="v3")
    send(robot, [{"actionType": "nope", "actionId": f"n{i}", "blockingType": "HARD"} for i in range(3)])

    (error,) = robot.errors
    assert [r["referenceValue"] for r in error["errorReferences"]] == ["n0", "n1", "n2"]


def test_instant_ids_stay_bounded_in_2_1():
    robot = Robot("robot_01")
    for i in range(3000):
        act(robot, "stateRequest", f"s-{i}")

    assert len(robot._instant_ids) <= MAX_INSTANT_ACTION_STATES
    assert len(robot.action_states) <= MAX_INSTANT_ACTION_STATES


@BOTH
def test_load_ids_do_not_grow_over_many_orders(major):
    robot = Robot("robot_01", vda_major=major)
    for i in range(5000):
        order = make_order(order_id=f"o-{i}", points=((0, 0),))
        order["nodes"][0]["actions"][0]["actionId"] = f"pick-{i}"
        assert robot.accept_order(order)
        robot.node_states = []
        robot.edge_states = []
        robot.action_states = []
    assert len(robot._load_ids) <= 5


# --- L1 -----------------------------------------------------------------


@BOTH
def test_duplicate_action_id_in_an_order_is_rejected(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["nodes"][1]["actions"][0]["actionId"] = order["nodes"][0]["actions"][0]["actionId"]

    assert robot.accept_order(order) is False
    assert types(robot) == ["validationError" if major == "v2" else "VALIDATION_FAILURE"]
    assert robot.order_id == ""


@BOTH
def test_duplicate_action_id_between_node_and_edge_is_rejected(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["edges"][0]["actions"] = [{"actionId": "a-pick", "actionType": "pick", "blockingType": "HARD"}]

    assert robot.accept_order(order) is False
    assert robot.order_id == ""


@BOTH
def test_duplicate_sequence_id_in_an_order_is_rejected(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order(points=((0, 0), (3, 4), (6, 8)))
    order["nodes"][2]["sequenceId"] = order["nodes"][1]["sequenceId"]

    assert robot.accept_order(order) is False
    assert types(robot) == ["validationError" if major == "v2" else "VALIDATION_FAILURE"]
    assert robot.order_id == ""


@BOTH
def test_instant_action_reusing_an_order_action_id_fails(major):
    robot = driving_robot(major)

    act(robot, "stateRequest", "a-drop")

    states = [a for a in [*robot.action_states, *robot.instant_action_states] if a["actionId"] == "a-drop"]
    failed = [a for a in states if a["actionStatus"] == "FAILED"]
    assert len(failed) == 1
    result = failed[0].get("actionResult", failed[0].get("resultDescription"))
    assert result == "actionId already in use"
    assert (major == "v3") == ("INVALID_INSTANT_ACTION" in types(robot))

    act(robot, "cancelOrder", "c-1")
    run(robot, 0.2)
    assert robot.idle
    assert not [a for a in robot.action_states if a["actionStatus"] == "WAITING"]
    # the order action is not touched by the duplicate: it was failed by the cancel, once
    assert robot.mission_status == "CANCELLED"


@BOTH
def test_instant_action_reusing_an_instant_id_fails(major):
    robot = Robot("robot_01", vda_major=major)
    act(robot, "stateRequest", "i-1")
    act(robot, "startPause", "i-1")

    assert robot.paused is False
    assert [a["actionStatus"] for a in instants(robot)] == ["FINISHED", "FAILED"]


@BOTH
def test_order_action_not_run_by_a_duplicate_instant_state(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(points=((0, 0), (3, 0))))
    act(robot, "stateRequest", "a-drop")
    robot.loads = [{"loadId": "L"}]
    run(robot, 5)

    assert robot.loads == []
    dup = [a for a in instants(robot) if a["actionType"] == "stateRequest"]
    assert dup[0]["actionStatus"] == "FAILED"


# --- L2 -----------------------------------------------------------------


class FakeConnection:
    def __init__(self, robot):
        self.robot = robot
        self.published = 0

    def apply_pending_messages(self):
        return False

    def publish_state(self):
        self.published += 1


@BOTH
def test_every_state_request_is_answered(major):
    robot = Robot("robot_01", vda_major=major)
    connection = FakeConnection(robot)
    step([connection], 1, 1000)  # nothing new
    base = connection.published
    for n in range(60):
        act(robot, "stateRequest", "same-id")
        step([connection], 2 + n, 1000)
    assert connection.published == base + 60
    step([connection], 100, 1000)
    assert connection.published == base + 60


# --- L3 -----------------------------------------------------------------


def test_update_with_the_same_id_after_cancel_is_a_cancel_error_in_3_0():
    robot = Robot("robot_01", vda_major="v3")
    order = horizon_order()
    robot.accept_order(order)
    robot.cancelled = True

    assert robot.accept_order(update_from(order, 1, 2, update_id=0)) is False
    assert types(robot) == ["ORDER_UPDATE_FOLLOWING_CANCEL"]


def test_update_with_the_same_id_after_cancel_is_still_ignored_in_2_1():
    robot = Robot("robot_01")
    order = horizon_order()
    robot.accept_order(order)
    robot.cancelled = True

    assert robot.accept_order(update_from(order, 1, 2, update_id=0)) is True
    assert robot.errors == []
