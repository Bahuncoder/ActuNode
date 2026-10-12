"""Untrusted input: id length bound, state size bound, D-31 payload limits, huge numbers."""

import json
import logging

import pytest

from simulator.protocol import (
    MAX_ACTIONS_PER_ORDER,
    MAX_EDGES_PER_ORDER,
    MAX_NODES_PER_ORDER,
    MAX_STATE_BYTES,
)
from simulator.protocol import MAX_PAYLOAD_BYTES as BROKER_LIMIT  # the broker's max_packet_size
from simulator.robot import MAX_ID_LENGTH, Robot
from simulator.tests.helpers import BOTH, make_order, send, snapshot, types

LONG = "x" * 200_000


def size(robot):
    return len(json.dumps(robot.state_message()))


def malformed(major):
    return "validationError" if major == "v2" else "VALIDATION_FAILURE"


def set_path(order, path, value):
    target = order
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


LONG_FIELDS = [
    ("orderId",),
    ("nodes", 0, "nodeId"),
    ("nodes", 0, "nodePosition", "mapId"),
    ("nodes", 0, "actions", 0, "actionId"),
    ("nodes", 0, "actions", 0, "actionType"),
    ("edges", 0, "edgeId"),
    ("edges", 0, "startNodeId"),
]


@BOTH
@pytest.mark.parametrize("path", LONG_FIELDS)
def test_over_long_order_ids_are_rejected_as_malformed(major, path):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    set_path(order, path, "y" * (MAX_ID_LENGTH + 1))

    assert robot.accept_order(order) is False

    assert types(robot) == [malformed(major)]
    assert size(robot) < 10_000
    for reference in robot.errors[0]["errorReferences"]:
        assert len(reference["referenceValue"]) <= MAX_ID_LENGTH + 1


@BOTH
def test_over_long_load_id_is_rejected_and_max_length_is_accepted(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    parameters = [{"key": "loadId", "value": "L" * (MAX_ID_LENGTH + 1)}]
    order["nodes"][0]["actions"][0]["actionParameters"] = parameters
    assert robot.accept_order(order) is False
    assert types(robot) == [malformed(major)]

    parameters[0]["value"] = "L" * MAX_ID_LENGTH
    assert robot.accept_order(order) is True


@BOTH
def test_over_long_instant_action_ids_and_types_are_ignored_with_one_log(major, caplog):
    robot = Robot("robot_01", vda_major=major)
    actions = [
        {"actionType": "bogus", "actionId": LONG[:100_000]},
        {"actionType": LONG[:100_000], "actionId": "a"},
        {"actionType": "stateRequest", "actionId": "ok"},
    ]
    with caplog.at_level(logging.WARNING):
        assert send(robot, actions) is True
    ids = [a["actionId"] for a in robot.state_message()["actionStates" if major == "v2" else "instantActionStates"]]
    assert ids == ["ok"]
    assert len([r for r in caplog.records if "2 instant actions" in r.getMessage()]) == 1


@BOTH
def test_worst_case_messages_keep_state_below_the_broker_limit(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order())
    for message in range(6):
        for length in (200_000, 5000, MAX_ID_LENGTH, MAX_ID_LENGTH):
            count = 1 if length == 200_000 else 50
            send(
                robot, [{"actionType": "bogus", "actionId": f"{message}-{k}".ljust(length, "q")} for k in range(count)]
            )
            assert size(robot) < BROKER_LIMIT


@BOTH
def test_state_guard_drops_oldest_finished_instant_states(major, monkeypatch):
    monkeypatch.setattr("simulator.messages.MAX_STATE_BYTES", 4000)
    robot = Robot("robot_01", vda_major=major)
    for i in range(40):
        send(robot, [{"actionType": "stateRequest", "actionId": f"{i:03}".ljust(MAX_ID_LENGTH, "z")}])
    state = robot.state_message()
    assert len(json.dumps(state)) <= 4000
    states = state["actionStates" if major == "v2" else "instantActionStates"]
    assert states and states[-1]["actionId"].startswith("039")


@BOTH
def test_factsheet_advertises_the_id_length(major):
    limits = Robot("robot_01", vda_major=major).factsheet_message()["protocolLimits"]
    lengths = limits["maxStringLens" if major == "v2" else "maximumStringLengths"]
    assert lengths["idLen" if major == "v2" else "maximumIdLength"] == MAX_ID_LENGTH
    assert lengths["loadIdLen" if major == "v2" else "maximumLoadIdLength"] == MAX_ID_LENGTH


# --- D-31 limits on the simulator's own parsing ---------------------------------


def nested(depth):
    return "[" * depth + "]" * depth


BAD_PAYLOADS = [
    b'{"pad":"' + b"x" * BROKER_LIMIT + b'"}',
    b'{"orderId": NaN}',
    b'{"orderId": Infinity}',
    nested(100_000).encode(),
    nested(33).encode(),
]


@BOTH
@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_orders_breaking_the_payload_limits_are_rejected_as_malformed(major, payload):
    robot = Robot("robot_01", vda_major=major)
    assert robot.handle_order_payload(payload) is False
    assert types(robot) == [malformed(major)]
    assert robot.errors[0]["errorDescription"]


@BOTH
@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_instant_actions_breaking_the_payload_limits_are_ignored(major, payload):
    robot = Robot("robot_01", vda_major=major)
    assert robot.handle_instant_actions_payload(payload) is False
    assert robot.errors == []


@BOTH
def test_order_nested_32_deep_still_parses(major):
    robot = Robot("robot_01", vda_major=major)
    assert robot.handle_order_payload(nested(32).encode()) is False  # parsed, then "not an object"
    assert "JSON object" in robot.errors[0]["errorDescription"]


# --- huge numbers ------------------------------------------------------------


@BOTH
@pytest.mark.parametrize("value", [10**400, -(10**400), 1e301])
def test_huge_numbers_reject_the_order_instead_of_raising(major, value):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["nodes"][0]["nodePosition"]["x"] = value
    assert robot.accept_order(order) is False
    assert types(robot) == [malformed(major)]


def test_more_than_50_instant_actions_log_the_dropped_count(caplog):
    robot = Robot("robot_01")
    with caplog.at_level(logging.WARNING):
        send(robot, [{"actionType": "stateRequest", "actionId": f"s{i}"} for i in range(53)])
    assert any("3 instant actions" in r.getMessage() for r in caplog.records)


# --- order size: nodes, edges and actions are counted across base and horizon, updates included -----------------


def chain_order(nodes, order_id="big", released=1, actions=0, long_ids=False):
    """`nodes` nodes in a row at the robot's position (so the first node is reachable); edges between them."""
    pad = (lambda text: text.ljust(MAX_ID_LENGTH, "x")) if long_ids else (lambda text: text)
    node_list = [
        {
            "nodeId": pad(f"N{i}"),
            "sequenceId": i * 2,
            "released": i < released,
            "nodePosition": {"x": 0.0, "y": 0.0, "mapId": "warehouse"},
            "actions": [{"actionId": pad(f"a{i}"), "actionType": "pick"}] if i < actions else [],
        }
        for i in range(nodes)
    ]
    edges = [
        {
            "edgeId": pad(f"E{i}"),
            "sequenceId": i * 2 - 1,
            "released": i < released,
            "startNodeId": pad(f"N{i - 1}"),
            "endNodeId": pad(f"N{i}"),
            "actions": [],
        }
        for i in range(1, nodes)
    ]
    order_id = pad(order_id) if long_ids else order_id
    return {"serialNumber": "robot_01", "orderId": order_id, "orderUpdateId": 0, "nodes": node_list, "edges": edges}


def continuation(order, first, nodes, update_id=1):
    """An update that restarts at node index `first` of `order` and then has `nodes` nodes in total."""
    update = chain_order(first + nodes, order["orderId"], released=first + 1)
    update["orderUpdateId"] = update_id
    update["nodes"] = update["nodes"][first:]
    update["edges"] = update["edges"][first:]
    return update


@BOTH
def test_order_with_the_most_nodes_is_accepted_and_one_more_is_malformed(major):
    robot = Robot("robot_01", vda_major=major)
    assert robot.accept_order(chain_order(MAX_NODES_PER_ORDER)) is True

    robot = Robot("robot_01", vda_major=major)
    assert robot.accept_order(chain_order(MAX_NODES_PER_ORDER + 1)) is False
    assert types(robot) == [malformed(major)]
    assert robot.order_id == "" and "nodes" in robot.errors[0]["errorDescription"]


@BOTH
def test_order_with_too_many_edges_or_actions_is_malformed(major):
    robot = Robot("robot_01", vda_major=major)
    order = chain_order(MAX_NODES_PER_ORDER)
    order["edges"] += [{"edgeId": f"X{i}", "sequenceId": 10_000 + i} for i in range(MAX_EDGES_PER_ORDER)]
    assert robot.accept_order(order) is False
    assert types(robot) == [malformed(major)] and "edges" in robot.errors[0]["errorDescription"]

    robot = Robot("robot_01", vda_major=major)
    order = chain_order(2)
    order["nodes"][1]["actions"] = [
        {"actionId": f"a{i}", "actionType": "pick"} for i in range(MAX_ACTIONS_PER_ORDER + 1)
    ]
    assert robot.accept_order(order) is False
    assert types(robot) == [malformed(major)] and "actions" in robot.errors[0]["errorDescription"]


@BOTH
def test_update_that_would_leave_too_many_nodes_is_malformed_and_changes_nothing(major):
    robot = Robot("robot_01", vda_major=major)
    order = chain_order(MAX_NODES_PER_ORDER, released=3)  # decision point: index 2; N1 and N2 stay
    assert robot.accept_order(order)
    before = snapshot(robot, "errors")

    # The update itself is within the limit, but 2 kept nodes + the limit minus 1 new ones are one too many.
    assert robot.accept_order(continuation(order, 2, MAX_NODES_PER_ORDER)) is False

    assert types(robot) == [malformed(major)]
    assert snapshot(robot, "errors") == before


@BOTH
def test_update_within_the_node_limit_is_accepted(major):
    robot = Robot("robot_01", vda_major=major)
    order = chain_order(MAX_NODES_PER_ORDER, released=3)
    assert robot.accept_order(order)

    assert robot.accept_order(continuation(order, 2, MAX_NODES_PER_ORDER - 1)) is True  # 2 kept + the rest new


@BOTH
def test_largest_accepted_order_keeps_the_state_below_the_state_and_broker_limits(major):
    robot = Robot("robot_01", vda_major=major)
    order = chain_order(MAX_NODES_PER_ORDER, actions=MAX_ACTIONS_PER_ORDER, long_ids=True)

    assert robot.accept_order(order) is True

    assert size(robot) < MAX_STATE_BYTES < BROKER_LIMIT
