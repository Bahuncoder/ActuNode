"""Order handling per D-35: error types, idle, first-node reachability, horizon, updates, edge actions, loads."""

import pytest

from simulator.robot import ACCEPTED, COMPLETED, MOVING, WAITING, Robot
from simulator.tests.helpers import (
    BOTH,
    act,
    horizon_order,
    make_order,
    official,
    run,
    run_until_done,
    types,
    update_from,
)

# --- 1. error types and persistence -------------------------------------


@pytest.mark.parametrize("major, expected", [("v2", "validationError"), ("v3", "VALIDATION_FAILURE")])
def test_malformed_order_error_type_by_version(major, expected):
    robot = Robot("robot_01", vda_major=major)
    assert not robot.accept_order({**make_order(), "nodes": []})
    assert types(robot) == [expected]
    assert robot.errors[0]["errorLevel"] == "WARNING"


@pytest.mark.parametrize("major, expected", [("v2", "orderError"), ("v3", "INVALID_ORDER_ACTION")])
def test_unsupported_action_type_names_the_field(major, expected):
    order = make_order()
    order["nodes"][1]["actions"] = [{"actionId": "x", "actionType": "lift", "blockingType": "HARD"}]
    robot = Robot("robot_01", vda_major=major)

    assert not robot.accept_order(order)

    assert types(robot) == [expected]
    assert {"referenceKey": "field", "referenceValue": "nodes[1].actions[0].actionType"} in robot.errors[0][
        "errorReferences"
    ]


def test_unsupported_edge_action_is_rejected_too():
    order = make_order()
    order["edges"][0]["actions"] = [{"actionId": "x", "actionType": "lift", "blockingType": "HARD"}]

    assert not Robot("robot_01").accept_order(order)


@pytest.mark.parametrize("major, expected", [("v2", "orderError"), ("v3", "OTHER_ORDER_ACTIVE")])
def test_new_order_while_active_by_version(major, expected):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(order_id="a"))

    assert not robot.accept_order(make_order(order_id="b"))

    assert types(robot) == [expected]


@pytest.mark.parametrize("major, expected", [("v2", "orderUpdateError"), ("v3", "OUTDATED_ORDER_UPDATE")])
def test_outdated_update_by_version(major, expected):
    robot = Robot("robot_01", vda_major=major)
    first = make_order()
    first["orderUpdateId"] = 3
    robot.accept_order(first)

    assert not robot.accept_order({**make_order(), "orderUpdateId": 2})

    assert types(robot) == [expected]


def test_same_update_id_with_other_content_v3_error_v2_ignored():
    changed = {**make_order(), "nodes": make_order(points=((0, 0), (3, 1)))["nodes"]}
    v3 = Robot("robot_01", vda_major="v3")
    v3.accept_order(make_order())
    v2 = Robot("robot_01")
    v2.accept_order(make_order())

    assert not v3.accept_order(changed)
    assert types(v3) == ["SAME_ORDER_UPDATE_ID"]
    assert v2.accept_order(changed) is True
    assert v2.errors == []


@BOTH
def test_identical_order_is_ignored_even_with_new_header(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order())

    assert robot.accept_order({**make_order(), "headerId": 9, "timestamp": "2026-01-01T00:00:00.000Z"})
    assert robot.errors == []


def test_rejection_stays_after_mission_completes_until_a_new_order_is_accepted():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="a"))
    robot.accept_order(make_order(order_id="b"))
    run_until_done(robot)

    assert robot.mission_status == COMPLETED
    assert types(robot) == ["orderError"]
    assert robot.accept_order(make_order(order_id="c", points=((3, 4),)))
    assert robot.errors == []


def test_accepted_update_clears_rejection():
    robot = Robot("robot_01")
    order = horizon_order()
    robot.accept_order(order)
    robot.accept_order({**make_order(), "orderId": "other"})
    assert types(robot) == ["orderError"]

    assert robot.accept_order(update_from(order, 1, 2))

    assert robot.errors == []


def test_update_after_cancel_is_rejected_by_version():
    for major, expected in (("v2", "orderUpdateError"), ("v3", "ORDER_UPDATE_FOLLOWING_CANCEL")):
        robot = Robot("robot_01", vda_major=major)
        order = horizon_order()
        robot.accept_order(order)
        act(robot, "cancelOrder")
        assert not robot.accept_order(update_from(order, 1, 2))
        assert types(robot) == [expected]


# --- 2. idle ------------------------------------------------------------


def test_idle_means_no_remaining_nodes_and_all_actions_done():
    robot = Robot("robot_01")
    assert robot.idle
    robot.accept_order(make_order())
    assert not robot.idle
    run_until_done(robot)
    assert robot.idle
    robot.action_states[0]["actionStatus"] = "RUNNING"
    assert not robot.idle
    robot.action_states[0]["actionStatus"] = "FAILED"
    assert robot.idle


def test_waiting_robot_is_not_idle_and_does_not_charge():
    robot = Robot("robot_01")
    robot.battery = 50
    robot.accept_order(horizon_order(released=1))
    run(robot, 1)

    assert robot.mission_status == WAITING
    assert not robot.idle
    assert robot.charging is False
    assert robot.battery == 50


# --- 3. first node reachability -----------------------------------------


@pytest.mark.parametrize("major, expected", [("v2", "orderError"), ("v3", "START_NODE_OUT_OF_RANGE")])
def test_far_first_node_is_rejected_by_version(major, expected):
    robot = Robot("robot_01", vda_major=major)

    assert not robot.accept_order(make_order(points=((3, 0), (3, 4))))

    assert types(robot) == [expected]
    assert robot.mission_status == "IDLE"


def test_default_tolerance_is_a_quarter_meter():
    assert Robot("robot_01", 0.2, 0).accept_order(make_order(points=((0, 0), (3, 0))))
    assert not Robot("robot_01", 0.3, 0).accept_order(make_order(points=((0, 0), (3, 0))))


def test_2_1_allowed_deviation_is_a_radius():
    order = make_order(points=((1.5, 0), (3, 0)))
    order["nodes"][0]["nodePosition"]["allowedDeviationXY"] = 2.0
    assert Robot("robot_01").accept_order(order)
    order["nodes"][0]["nodePosition"]["allowedDeviationXY"] = 0
    assert not Robot("robot_01").accept_order(order)


def test_3_0_allowed_deviation_is_a_rotated_ellipse():
    def accepts(theta):
        order = make_order(points=((1.5, 0), (3, 0)))
        order["nodes"][0]["nodePosition"]["allowedDeviationXY"] = {"a": 2.0, "b": 0.1, "theta": theta}
        return Robot("robot_01", vda_major="v3").accept_order(order)

    assert accepts(0.0)  # long axis along x: 1.5 m away on x is inside
    assert not accepts(1.5707963)  # long axis along y


@pytest.mark.parametrize(
    "major, value", [("v2", {"a": 1, "b": 1, "theta": 0}), ("v2", "1"), ("v3", 1.0), ("v3", {"a": 1})]
)
def test_allowed_deviation_of_the_wrong_type_is_malformed(major, value):
    order = make_order()
    order["nodes"][0]["nodePosition"]["allowedDeviationXY"] = value
    robot = Robot("robot_01", vda_major=major)

    assert not robot.accept_order(order)

    assert types(robot) == ["validationError" if major == "v2" else "VALIDATION_FAILURE"]


@BOTH
def test_first_node_counts_as_traversed_at_acceptance(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(points=((0.1, 0), (3, 0))))

    state = robot.state_message()
    assert (state["lastNodeId"], state["lastNodeSequenceId"]) == ("N0", 0)
    assert [n["nodeId"] for n in state["nodeStates"]] == ["N1"]
    assert state["actionStates"][0]["actionStatus"] == "FINISHED"  # N0's pick ran


# --- 4. horizon ---------------------------------------------------------


@BOTH
def test_robot_stops_at_the_decision_point_and_waits(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(horizon_order())
    run(robot, 5)

    state = robot.state_message()
    assert robot.mission_status == WAITING
    assert state["actunode"]["missionStatus"] == WAITING
    assert (robot.x, robot.y) == (2, 0)
    assert state["driving"] is False
    assert (state["lastNodeId"], state["lastNodeSequenceId"]) == ("N1", 2)
    assert [(n["nodeId"], n["released"]) for n in state["nodeStates"]] == [("N2", False), ("N3", False)]
    assert [(e["edgeId"], e["released"]) for e in state["edgeStates"]] == [("N1->N2", False), ("N2->N3", False)]
    assert state["newBaseRequest"] is True


def test_new_base_request_only_within_one_meter_of_the_decision_point():
    robot = Robot("robot_01")
    robot.accept_order(horizon_order())
    run(robot, 0.5)
    assert robot.state_message()["newBaseRequest"] is False
    run(robot, 0.6)
    assert robot.state_message()["newBaseRequest"] is True


def test_no_new_base_request_without_horizon_and_order_unchanged():
    robot = Robot("robot_01")
    robot.accept_order(horizon_order(released=4))
    assert robot.state_message()["newBaseRequest"] is False
    run(robot, 20)
    assert robot.mission_status == COMPLETED
    assert robot.state_message()["newBaseRequest"] is False


def test_horizon_actions_stay_waiting_and_node_in_base_finishes():
    robot = Robot("robot_01")
    robot.accept_order(horizon_order())
    run(robot, 5)

    status = {a["actionId"]: a["actionStatus"] for a in robot.state_message()["actionStates"]}
    assert status == {"act-N1": "FINISHED", "e-1": "FINISHED"}


# --- 5. order updates ---------------------------------------------------


@BOTH
def test_update_at_the_decision_point_resumes_and_completes(major):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    robot.accept_order(order)
    run(robot, 5)
    update = update_from(order, 1, 2)

    assert robot.accept_order(update)

    assert robot.order_update_id == 1
    assert robot.mission_status == MOVING
    assert [(n["nodeId"], n["released"]) for n in robot.state_message()["nodeStates"]] == [
        ("N2", True),
        ("N3", False),
    ]
    run(robot, 5)
    assert robot.mission_status == WAITING
    assert (robot.x, robot.y) == (2, 3)


def test_update_does_not_rerun_the_stitch_nodes_actions():
    robot = Robot("robot_01")
    order = horizon_order()
    robot.accept_order(order)
    run(robot, 5)
    robot.action_states[0]["actionStatus"] = "FINISHED"
    robot.accept_order(update_from(order, 1, 2))

    assert [a["actionId"] for a in robot.action_states].count("act-N1") == 1
    assert next(a for a in robot.action_states if a["actionId"] == "act-N1")["actionStatus"] == "FINISHED"


def test_update_replaces_the_horizon_and_its_actions():
    robot = Robot("robot_01")
    order = horizon_order()
    order["nodes"][3]["actions"] = [{"actionId": "old-h", "actionType": "pick", "blockingType": "HARD"}]
    robot.accept_order(order)
    run(robot, 5)
    update = update_from(order, 1, 2)
    update["nodes"][-1]["nodeId"] = "N9"
    update["nodes"][-1]["actions"] = [{"actionId": "new-h", "actionType": "pick", "blockingType": "HARD"}]

    assert robot.accept_order(update)

    ids = [a["actionId"] for a in robot.action_states]
    assert "old-h" not in ids and "new-h" in ids
    assert [n["nodeId"] for n in robot.node_states] == ["N2", "N9"]
    assert robot.mission_status == MOVING


def test_update_stitching_at_an_untraversed_decision_point_keeps_its_actions():
    robot = Robot("robot_01")
    order = horizon_order()
    robot.accept_order(order)
    run(robot, 0.5)  # still on the way to N1

    assert robot.accept_order(update_from(order, 1, 2))

    run(robot, 5)
    assert next(a for a in robot.action_states if a["actionId"] == "act-N1")["actionStatus"] == "FINISHED"
    assert robot.mission_status == WAITING


@pytest.mark.parametrize("major, expected", [("v2", "orderUpdateError"), ("v3", "VALIDATION_FAILURE")])
def test_update_that_does_not_stitch_is_rejected_by_version(major, expected):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    robot.accept_order(order)
    run(robot, 5)
    bad = update_from(order, 2, 3)  # starts at N2, but the decision point is N1

    assert not robot.accept_order(bad)

    assert types(robot) == [expected]
    assert robot.order_update_id == 0
    assert robot.mission_status == WAITING


def test_update_for_a_completed_order_stitches_at_last_node():
    robot = Robot("robot_01")
    order = horizon_order(released=2)
    order["nodes"] = order["nodes"][:2]
    order["edges"] = order["edges"][:1]
    robot.accept_order(order)
    run_until_done(robot)
    full = horizon_order()

    assert robot.accept_order(update_from(full, 1, 2))

    assert robot.mission_status == ACCEPTED
    run(robot, 5)
    assert robot.mission_status == WAITING
    assert robot.last_node_id == "N2"


# --- 6. edge actions ----------------------------------------------------


def test_edge_action_waits_runs_on_the_edge_and_finishes_at_its_end_node():
    robot = Robot("robot_01")
    robot.accept_order(horizon_order(released=4))

    def edge_status():
        return next(a["actionStatus"] for a in robot.action_states if a["actionId"] == "e-1")

    assert edge_status() == "RUNNING"  # N0 (its start node) is traversed at acceptance
    run(robot, 1)
    assert edge_status() == "RUNNING"
    run(robot, 1.5)  # past N1
    assert edge_status() == "FINISHED"


def test_horizon_edge_action_is_not_started():
    robot = Robot("robot_01")
    order = horizon_order(released=1)
    robot.accept_order(order)
    assert next(a["actionStatus"] for a in robot.action_states if a["actionId"] == "e-1") == "WAITING"


# --- 7. loads -----------------------------------------------------------


def with_load_id(order, action_id, load_id):
    for node in order["nodes"]:
        for action in node["actions"]:
            if action["actionId"] == action_id:
                action["actionParameters"] = [{"key": "loadId", "value": load_id}]
    return order


@BOTH
def test_loads_follow_pick_and_drop(major):
    robot = Robot("robot_01", vda_major=major)
    assert robot.state_message()["loads"] == []
    robot.accept_order(with_load_id(make_order(points=((0, 0), (3, 0))), "a-pick", "P-1"))

    assert robot.state_message()["loads"] == [{"loadId": "P-1"}]
    run_until_done(robot)
    assert robot.state_message()["loads"] == []


def test_pick_without_load_id_uses_empty_string():
    robot = Robot("robot_01")
    robot.accept_order(make_order())

    assert robot.state_message()["loads"] == [{"loadId": ""}]


@BOTH
def test_pick_while_loaded_and_drop_while_empty_fail(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(points=((0, 0), (3, 0))))
    run_until_done(robot)
    robot.accept_order(make_order(order_id="o2", points=((3, 0), (3, 4))))  # picks (loaded? no: dropped before)
    run_until_done(robot)
    assert robot.state_message()["loads"] == []

    # drop on an empty robot
    empty = Robot("robot_01", vda_major=major)
    order = make_order(points=((0, 0), (3, 0)))
    order["nodes"][0]["actions"] = []
    empty.accept_order(order)
    run_until_done(empty)
    drop = empty.state_message()["actionStates"][0]
    assert drop["actionStatus"] == "FAILED"
    assert drop["resultDescription" if major == "v2" else "actionResult"]

    # pick while loaded
    loaded = Robot("robot_01", vda_major=major)
    order = make_order(points=((0, 0), (3, 0)))
    order["nodes"][1]["actions"] = [{"actionId": "p2", "actionType": "pick", "blockingType": "HARD"}]
    loaded.accept_order(order)
    run_until_done(loaded)
    assert [a["actionStatus"] for a in loaded.state_message()["actionStates"]] == ["FINISHED", "FAILED"]
    assert loaded.state_message()["loads"] == [{"loadId": ""}]
    assert loaded.idle


# --- 9. event signature -------------------------------------------------


def test_event_signature_reports_new_base_request_and_loads():
    robot = Robot("robot_01")
    robot.accept_order(horizon_order())
    run(robot, 0.5)
    before = robot.event_signature()
    run(robot, 0.6)  # crosses the 1 m mark
    assert robot.event_signature() != before
    loaded = Robot("robot_01")
    unloaded = loaded.event_signature()
    loaded.loads = [{"loadId": "x"}]
    assert loaded.event_signature() != unloaded


# --- 8. state validates in every new situation ---------------------------


def new_situation_states(major):
    """(label, state) for every new situation."""
    out = []
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    robot.accept_order(order)
    out.append(("accepted with horizon", robot.state_message()))
    run(robot, 5)
    out.append(("waiting", robot.state_message()))
    robot.accept_order(update_from(order, 1, 2))
    out.append(("after update", robot.state_message()))
    run(robot, 20)
    out.append(("waiting again", robot.state_message()))
    loaded = Robot("robot_01", vda_major=major)
    loaded.accept_order(with_load_id(make_order(points=((0, 0), (3, 0))), "a-pick", "P-1"))
    out.append(("loaded", loaded.state_message()))
    run_until_done(loaded)
    out.append(("dropped", loaded.state_message()))
    failed = Robot("robot_01", vda_major=major)
    bad = make_order(points=((0, 0), (3, 0)))
    bad["nodes"][0]["actions"] = []
    failed.accept_order(bad)
    run_until_done(failed)
    out.append(("failed drop", failed.state_message()))

    def rejected(label, mutate=lambda o: None, setup=lambda r: None, order=None):
        r = Robot("robot_01", vda_major=major)
        setup(r)
        o = order or make_order(order_id="rej")
        mutate(o)
        r.accept_order(o)
        out.append((label, r.state_message()))

    rejected("malformed", lambda o: o.update(nodes=[]))
    rejected(
        "bad action",
        lambda o: o["nodes"][1]["actions"].append({"actionId": "q", "actionType": "lift", "blockingType": "NONE"}),
    )
    rejected("out of range", order=make_order(points=((9, 9), (3, 0))))
    rejected("other order active", setup=lambda r: r.accept_order(make_order(order_id="first")))

    def second(r):
        first = make_order(order_id="rej")
        first["orderUpdateId"] = 5
        r.accept_order(first)

    rejected("outdated", setup=second)
    rejected(
        "same id",
        lambda o: o["nodes"][1].update(nodeId="Z"),
        setup=lambda r: r.accept_order(make_order(order_id="rej")),
    )
    return out


@pytest.mark.parametrize("major", ["v2", "v3"])
def test_states_in_every_new_situation_pass_the_official_schema(major):
    failures = []
    for label, state in new_situation_states(major):
        for error in official(major, "state").iter_errors(state):
            failures.append(f"{label} /{'/'.join(map(str, error.absolute_path))}: {error.message}")
    assert not failures, "\n".join(failures)
