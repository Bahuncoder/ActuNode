"""Behaviour the VDA 5050 schema leaves open, that master control software depends on.

From a master-control engineer's list of what breaks most often between fleet control and robots (D-69).
"""

from simulator.messages import factsheet_message
from simulator.robot import COMPLETED, Robot
from simulator.tests.helpers import BOTH, act, driving_robot, make_order, run, run_until_done, send, status


def declared_instant_actions(robot):
    """(actionType, parameter keys) of every INSTANT-scope action in the robot's factsheet."""
    features = factsheet_message(robot)["protocolFeatures"]
    actions = next(value for key, value in features.items() if key != "optionalParameters")
    return [
        (a["actionType"], [p["key"] for p in a.get("actionParameters", [])])
        for a in actions
        if "INSTANT" in a["actionScopes"]
    ]


def three_node_robot(major):
    robot = Robot("robot_01", vda_major=major)
    assert robot.accept_order(make_order(order_id="o-1", points=((0, 0), (10, 0), (10, 10))))
    run(robot, 2)  # between N0 and N1
    return robot


@BOTH
def test_last_node_id_changes_only_on_arrival(major):
    """While the robot drives between two nodes, lastNodeId is still the node it left."""
    robot = three_node_robot(major)
    state = robot.state_message()

    assert state["driving"] is True and 0 < robot.x < 10
    assert (state["lastNodeId"], state["lastNodeSequenceId"]) == ("N0", 0)
    run(robot, 9)
    state = robot.state_message()
    assert (state["lastNodeId"], state["lastNodeSequenceId"]) == ("N1", 2)


@BOTH
def test_cancel_order_keeps_last_node_and_robot_stays_put(major):
    """After cancelOrder the robot keeps the last node it reached, has no work left and does not move."""
    robot = three_node_robot(major)
    act(robot, "cancelOrder")
    state = robot.state_message()
    position = (robot.x, robot.y)

    assert (state["lastNodeId"], state["lastNodeSequenceId"]) == ("N0", 0)
    assert state["nodeStates"] == [] and state["edgeStates"] == []
    assert state["driving"] is False and state["orderId"] == "o-1"
    run(robot, 3)
    assert (robot.x, robot.y) == position
    assert robot.state_message()["driving"] is False


@BOTH
def test_restarted_robot_knows_no_order(major):
    """A restarted robot (a new Robot) reports an empty lastNodeId and orderId (the simulator's choice)."""
    state = Robot("robot_01", vda_major=major).state_message()

    assert state["lastNodeId"] == "" and state["orderId"] == ""


@BOTH
def test_pause_freezes_the_robot_and_resume_finishes_the_order(major):
    """A paused robot stands still with paused true and the same lastNodeId; after stopPause the order completes."""
    robot = three_node_robot(major)
    act(robot, "startPause", "p1")
    position = (robot.x, robot.y)
    run(robot, 3)
    state = robot.state_message()

    assert state["paused"] is True and state["driving"] is False
    assert (robot.x, robot.y) == position and state["lastNodeId"] == "N0"

    act(robot, "stopPause", "p2")
    run_until_done(robot)
    state = robot.state_message()
    assert state["paused"] is False and robot.mission_status == COMPLETED
    assert state["nodeStates"] == [] and state["lastNodeId"] == "N2"


@BOTH
def test_order_with_failed_action_still_finishes(major):
    """An order whose drop fails (no load) is finished: no node or edge states, every action FINISHED or FAILED."""
    robot = Robot("robot_01", vda_major=major)
    order = make_order(points=((0, 0), (3, 0)))
    order["nodes"][0]["actions"] = []  # no pick first: the robot has no load to drop
    robot.accept_order(order)
    run_until_done(robot)
    state = robot.state_message()
    drop = next(a for a in state["actionStates"] if a["actionId"] == "a-drop")

    assert state["nodeStates"] == [] and state["edgeStates"] == []
    assert drop["actionStatus"] == "FAILED" and drop[robot.v.result_key]
    assert {a["actionStatus"] for a in state["actionStates"]} <= {"FINISHED", "FAILED"}
    assert robot.mission_status == COMPLETED
    assert state["driving"] is False


@BOTH
def test_factsheet_matches_what_the_robot_accepts(major):
    """Every instant action the factsheet declares is accepted; one it does not declare is FAILED as unsupported."""
    declared = declared_instant_actions(Robot("robot_01", vda_major=major))
    assert declared

    for index, (action_type, keys) in enumerate(declared):
        robot = driving_robot(major)  # cancelOrder needs an order to cancel
        assert all(key == key.strip() and key[:1].islower() and "_" not in key for key in keys)
        parameters = {"orderId": "o-1"} if "orderId" in keys else {}
        act(robot, action_type, f"d-{index}", **parameters)
        assert status(robot, f"d-{index}") != "FAILED", action_type

    robot = Robot("robot_01", vda_major=major)
    send(robot, [{"actionType": "selfDestruct", "actionId": "x-1", "blockingType": "HARD"}])
    assert status(robot, "x-1") == "FAILED"
    assert "selfDestruct" not in {t for t, _ in declared}
    assert "unsupported" in next(a for a in robot.instant_action_states if a["actionId"] == "x-1")[robot.v.result_key]


@BOTH
def test_order_on_another_map_is_rejected_naming_the_map(major):
    """An order whose nodes sit on a map the robot does not know is rejected, and the error names the mapId."""
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["nodes"][1]["nodePosition"]["mapId"] = "basement"

    assert robot.accept_order(order) is False
    assert len(robot.errors) == 1
    assert "mapId" in robot.errors[0]["errorDescription"] and "basement" in robot.errors[0]["errorDescription"]
    assert robot.state_message()["orderId"] == ""
