"""Fixes of the 2026-10-14 audit, section S (docs/AUDIT_2026-10-14.md): one group of tests per finding."""

import copy
import json
import threading
import time
from types import SimpleNamespace

import pytest

from simulator import __main__ as sim_main
from simulator import publisher
from simulator.publisher import RobotConnection
from simulator.robot import COMPLETED, FAILED, Robot
from simulator.tests.helpers import BOTH, horizon_order, make_order, official, run, types, update_from

VALIDATION = {"v2": "validationError", "v3": "VALIDATION_FAILURE"}


def node(node_id, seq, x, y, released=True, actions=()):
    return {
        "nodeId": node_id,
        "sequenceId": seq,
        "released": released,
        "nodePosition": {"x": x, "y": y, "mapId": "warehouse"},
        "actions": list(actions),
    }


def edge(edge_id, seq, released=True, start=None, end=None):
    result = {"edgeId": edge_id, "sequenceId": seq, "released": released, "actions": []}
    if start:  # 2.1 edges name their end nodes
        result |= {"startNodeId": start, "endNodeId": end}
    return result


def action(action_id, action_type="pick"):
    return {"actionId": action_id, "actionType": action_type, "blockingType": "HARD"}


def order_of(nodes, edges, order_id="o", update_id=0):
    return {"serialNumber": "robot_01", "orderId": order_id, "orderUpdateId": update_id, "nodes": nodes, "edges": edges}


def connection_with(robot=None):
    return RobotConnection(robot or Robot("robot_01"), "127.0.0.1", 1)


def message(topic_name, payload=b"{}"):
    return SimpleNamespace(topic=topic_name, payload=payload)


# --- S1: bounded inbox, per-tick budget, instant actions first, no whole-robot copy -----------------------------


def test_inbox_is_bounded_and_counts_what_it_drops():
    connection = connection_with()
    for _ in range(publisher.INBOX_MAX + 20):
        connection._on_message(None, None, message(connection.order_topic))

    assert connection.inbox.qsize() == publisher.INBOX_MAX
    assert connection.dropped == 20


def test_a_tick_applies_only_a_few_messages():
    connection = connection_with()
    for _ in range(40):
        connection._on_message(None, None, message(connection.order_topic))

    assert connection.apply_pending_messages() is True
    assert connection.inbox.qsize() == 40 - publisher.MAX_MESSAGES_PER_TICK


def test_a_tick_stops_at_its_time_budget(monkeypatch):
    connection = connection_with()
    monkeypatch.setattr(connection.robot, "handle_order_payload", lambda payload: time.sleep(0.03) or True)
    for _ in range(4):
        connection._on_message(None, None, message(connection.order_topic))

    connection.apply_pending_messages()

    assert connection.inbox.qsize() == 3


def test_cancel_order_does_not_wait_behind_orders():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (10, 0))))
    run(robot, 1)
    connection = connection_with(robot)
    for _ in range(publisher.INBOX_MAX):
        connection._on_message(None, None, message(connection.order_topic, b"{}"))
    cancel = {"actions": [{"actionType": "cancelOrder", "actionId": "c", "blockingType": "NONE"}]}
    connection._on_message(None, None, message(connection.instant_topic, json.dumps(cancel).encode()))

    connection.apply_pending_messages()

    assert robot.mission_status == "CANCELLED"


def test_a_flooded_inbox_never_blocks_the_callback_thread_or_the_instant_queue():
    connection = connection_with()
    for _ in range(publisher.INBOX_MAX + 5):
        connection._on_message(None, None, message(connection.order_topic))
    connection._on_message(None, None, message(connection.instant_topic))  # not shut out by the full order queue

    assert connection.instant_inbox.qsize() == 1


class NoCopy:
    def __deepcopy__(self, memo):
        raise AssertionError("the whole robot must not be deep-copied for one order")


@BOTH
def test_accepting_an_order_does_not_copy_the_whole_robot(major):
    robot = Robot("robot_01", vda_major=major)
    robot.unrelated = NoCopy()

    assert robot.accept_order(make_order()) is True


# --- S2: no growth in a long-running order ----------------------------------------------------------------------


def test_no_empty_entries_and_actions_leave_the_maps_when_traversed():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (3, 0))))
    assert robot._node_actions == {2: ["a-drop"]} and robot._edge_actions == {}

    run(robot, 5)

    assert robot._node_actions == {} and robot._edge_actions == {}
    assert [a["actionStatus"] for a in robot.action_states] == ["FINISHED", "FINISHED"]


def test_3000_updates_of_one_order_cost_the_same_each():
    robot = Robot("robot_01")
    robot.accept_order(order_of([node("N0", 0, 0, 0)], []))
    seq, durations = 0, []
    for uid in range(1, 3001):
        nodes = [node(f"N{seq}", seq, 0, 0), *(node(f"N{seq + 2 * k}", seq + 2 * k, 0, 0) for k in range(1, 4))]
        edges = [
            edge(f"E{seq + 2 * k - 1}", seq + 2 * k - 1, start=nodes[k - 1]["nodeId"], end=nodes[k]["nodeId"])
            for k in range(1, 4)
        ]
        started = time.perf_counter()
        assert robot.accept_order(order_of(nodes, edges, "o", uid)), robot.errors
        durations.append(time.perf_counter() - started)
        robot.update(0.1)
        seq += 6

    assert sum(durations[-100:]) / 100 < 0.005
    assert len(robot._node_actions) + len(robot._edge_actions) <= 4


# --- S3, S11, S13: the order graph and the header ---------------------------------------------------------------


def three(**changes):
    """N0 (0,0) -> N1 (3,0) -> N2 (6,0), valid for both versions' shapes (edges name their nodes: 3.0 ignores it)."""
    nodes = [node("N0", 0, 0, 0), node("N1", 2, 3, 0), node("N2", 4, 6, 0)]
    edges = [edge("E1", 1, start="N0", end="N1"), edge("E2", 3, start="N1", end="N2")]
    return nodes, edges


def ghost_edge(nodes, edges):
    edges.append(edge("Ghost", 99, start="N2", end="N2"))


def odd_node(nodes, edges):
    nodes[1]["sequenceId"] = 3


def start_not_zero(nodes, edges):
    for item in nodes + edges:
        item["sequenceId"] += 2


def gap(nodes, edges):
    nodes[2]["sequenceId"] = 6


def too_few_edges(nodes, edges):
    edges.pop()


def edge_in_wrong_place(nodes, edges):
    edges[0]["sequenceId"] = 5


def released_after_unreleased(nodes, edges):
    nodes[1]["released"] = edges[0]["released"] = False


def first_unreleased(nodes, edges):
    for item in nodes + edges:
        item["released"] = False


def missing_released_node(nodes, edges):
    del nodes[1]["released"]


def missing_released_edge(nodes, edges):
    del edges[1]["released"]


BAD_GRAPHS = [
    ghost_edge,
    odd_node,
    start_not_zero,
    gap,
    too_few_edges,
    edge_in_wrong_place,
    released_after_unreleased,
    first_unreleased,
    missing_released_node,
    missing_released_edge,
]


@BOTH
@pytest.mark.parametrize("bad", BAD_GRAPHS, ids=lambda f: f.__name__)
def test_a_malformed_graph_is_rejected_and_the_robot_stays_free(major, bad):
    robot = Robot("robot_01", vda_major=major)
    nodes, edges = three()
    bad(nodes, edges)

    assert robot.accept_order(order_of(nodes, edges)) is False

    assert types(robot) == [VALIDATION[major]]
    assert robot.idle and robot.order_id == ""
    assert robot.accept_order(make_order(order_id="next")) is True


def test_released_after_unreleased_is_caught_in_the_order_the_nodes_and_edges_run():
    robot = Robot("robot_01")
    nodes, edges = three()
    nodes[1]["released"] = False  # N1 unreleased, but the edge before it and N2 are released
    assert robot.accept_order(order_of(nodes, edges)) is False


def test_2_1_edge_must_name_its_neighbouring_nodes():
    robot = Robot("robot_01")
    nodes, edges = three()
    edges[1]["endNodeId"] = "elsewhere"

    assert robot.accept_order(order_of(nodes, edges)) is False
    assert types(robot) == ["validationError"]


def test_3_0_edges_need_no_end_nodes():
    robot = Robot("robot_01", vda_major="v3")
    nodes, edges = three()
    for item in edges:
        del item["startNodeId"], item["endNodeId"]

    assert robot.accept_order(order_of(nodes, edges)) is True


@BOTH
def test_a_malformed_update_graph_is_rejected_without_a_change(major):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    robot.accept_order(order)
    run(robot, 5)  # waiting at N1, the decision point
    update = update_from(order, 1, 3)
    update["edges"][0]["sequenceId"] = 7  # not between N1 and N2

    assert robot.accept_order(update) is False
    assert types(robot) == [VALIDATION[major]]
    assert [n["nodeId"] for n in robot.node_states] == ["N2", "N3"]


# The orders the backend (build_order, build_order_update; fixtures order.json and v3_order.json) and the example fleet
# manager send must keep being accepted.
BACKEND_ORDER_V2 = {
    "headerId": 1,
    "timestamp": "2026-10-09T21:55:57.860Z",
    "version": "2.1.0",
    "manufacturer": "ActuNode",
    "serialNumber": "robot_01",
    "orderId": "order-bcb609db",
    "orderUpdateId": 0,
    "nodes": [
        {
            "nodeId": "RECEIVING_DOOR_2",
            "sequenceId": 0,
            "released": True,
            "nodePosition": {"x": 2.0, "y": 14.0, "mapId": "warehouse"},
            "actions": [
                {
                    "actionType": "pick",
                    "actionId": "order-bcb609db-pick",
                    "blockingType": "HARD",
                    "actionParameters": [{"key": "loadId", "value": "P-1042"}],
                }
            ],
        },
        {
            "nodeId": "STORAGE_A17",
            "sequenceId": 2,
            "released": True,
            "nodePosition": {"x": 14.0, "y": 18.0, "mapId": "warehouse"},
            "actions": [
                {
                    "actionType": "drop",
                    "actionId": "order-bcb609db-drop",
                    "blockingType": "HARD",
                    "actionParameters": [{"key": "loadId", "value": "P-1042"}],
                }
            ],
        },
    ],
    "edges": [
        {
            "edgeId": "RECEIVING_DOOR_2->STORAGE_A17",
            "sequenceId": 1,
            "released": True,
            "startNodeId": "RECEIVING_DOOR_2",
            "endNodeId": "STORAGE_A17",
            "actions": [],
        }
    ],
}
BACKEND_ORDER_V3 = {
    "headerId": 1,
    "timestamp": "2026-10-10T12:00:00.000Z",
    "version": "3.0.0",
    "manufacturer": "ActuNode",
    "serialNumber": "robot_01",
    "orderId": "order-31",
    "orderUpdateId": 0,
    "nodes": [
        {
            "nodeId": "A",
            "sequenceId": 0,
            "released": True,
            "nodePosition": {"x": 1, "y": 2, "mapId": "warehouse"},
            "actions": [],
        },
        {
            "nodeId": "B",
            "sequenceId": 2,
            "released": True,
            "nodePosition": {"x": 5, "y": 2, "mapId": "warehouse"},
            "actions": [{"actionType": "drop", "actionId": "d1", "blockingType": "HARD"}],
        },
    ],
    "edges": [{"edgeId": "A-B", "sequenceId": 1, "released": True, "actions": []}],
}


def test_the_backend_order_shape_is_accepted_and_extended_in_2_1():
    robot = Robot("robot_01", 2.0, 14.0)
    assert robot.accept_order(copy.deepcopy(BACKEND_ORDER_V2)), robot.errors
    run(robot, 25)
    assert robot.mission_status == COMPLETED
    # build_order_update: the last released node again, and one more stop after it.
    stitch = copy.deepcopy(BACKEND_ORDER_V2["nodes"][1])
    stitch["actions"] = BACKEND_ORDER_V2["nodes"][1]["actions"]
    update = {
        **BACKEND_ORDER_V2,
        "orderUpdateId": 1,
        "nodes": [stitch, node("DOCK", 4, 14, 10)],
        "edges": [edge("STORAGE_A17->DOCK", 3, start="STORAGE_A17", end="DOCK")],
    }
    assert robot.accept_order(update), robot.errors


def test_the_backend_order_shape_is_accepted_and_extended_in_3_0():
    robot = Robot("robot_01", 1.0, 2.0, vda_major="v3")
    assert robot.accept_order(copy.deepcopy(BACKEND_ORDER_V3)), robot.errors
    run(robot, 10)
    assert robot.mission_status == COMPLETED
    update = {
        **BACKEND_ORDER_V3,
        "orderUpdateId": 1,
        "nodes": [copy.deepcopy(BACKEND_ORDER_V3["nodes"][1]), node("C", 4, 8, 2)],
        "edges": [{"edgeId": "B-C", "sequenceId": 3, "released": True, "actions": []}],
    }
    assert robot.accept_order(update), robot.errors


def test_the_example_fleet_manager_order_is_accepted():
    robot = Robot("robot_01", 0, 0)
    stops = [("start", 0, 0), ("detour", 2, 3), ("dest", 5, 3)]
    nodes = [node(name, 2 * i, x, y) for i, (name, x, y) in enumerate(stops)]
    edges = [
        edge(f"{a['nodeId']}->{b['nodeId']}", 2 * i + 1, start=a["nodeId"], end=b["nodeId"])
        for i, (a, b) in enumerate(zip(nodes, nodes[1:], strict=False))
    ]

    assert robot.accept_order(order_of(nodes, edges, "example-robot_01-1-1")), robot.errors


@BOTH
def test_released_is_required(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    del order["nodes"][1]["released"]

    assert robot.accept_order(order) is False
    assert types(robot) == [VALIDATION[major]]


@BOTH
def test_an_order_whose_first_node_is_unreleased_is_rejected_and_runs_nothing(major):
    robot = Robot("robot_01", vda_major=major)
    nodes = [node("N0", 0, 0, 0, released=False, actions=[action("p")]), node("N1", 2, 2, 0, released=False)]
    edges = [edge("E1", 1, released=False, start="N0", end="N1")]

    assert robot.accept_order(order_of(nodes, edges)) is False
    assert robot.loads == []


@BOTH
def test_order_for_another_version_or_manufacturer_is_rejected(major):
    robot = Robot("robot_01", vda_major=major)
    other_version = "3.0.0" if major == "v2" else "2.1.0"
    for changes in ({"version": other_version}, {"version": 2}, {"manufacturer": "SomeoneElse"}):
        assert robot.accept_order({**make_order(), **changes}) is False
        assert types(robot) == [VALIDATION[major]]
    version = robot.v.protocol_version
    assert robot.accept_order({**make_order(), "version": version, "manufacturer": "ActuNode"}) is True


@BOTH
def test_unknown_map_is_rejected_and_the_known_one_is_echoed(major):
    robot = Robot("robot_01", vda_major=major)
    order = make_order()
    order["nodes"][1]["nodePosition"]["mapId"] = "basement"
    assert robot.accept_order(order) is False
    assert types(robot) == [VALIDATION[major]]

    assert robot.accept_order(make_order()) is True
    assert {n["nodePosition"]["mapId"] for n in robot.state_message()["nodeStates"]} == {"warehouse"}


# --- S4: an update may not reuse an actionId the order keeps ------------------------------------------------------


def with_pending_pick(major):
    robot = Robot("robot_01", vda_major=major)
    nodes = [node("N0", 0, 0, 0), node("N1", 2, 5, 0, actions=[action("a1")]), node("N2", 4, 10, 0)]
    edges = [edge("E1", 1, start="N0", end="N1"), edge("E2", 3, start="N1", end="N2")]
    assert robot.accept_order(order_of(nodes, edges))
    run(robot, 1)
    return robot


@BOTH
def test_update_reusing_a_kept_action_id_is_rejected(major):
    robot = with_pending_pick(major)
    update = order_of(
        [node("N2", 4, 10, 0), node("N3", 6, 12, 0, actions=[action("a1", "drop")])],
        [edge("E3", 5, start="N2", end="N3")],
        update_id=1,
    )

    assert robot.accept_order(update) is False
    assert types(robot) == ["orderUpdateError" if major == "v2" else "VALIDATION_FAILURE"]
    assert [a["actionType"] for a in robot.action_states] == ["pick"]


@BOTH
def test_update_may_resend_the_replaced_horizons_action_ids(major):
    robot = Robot("robot_01", vda_major=major)
    order = horizon_order()
    order["nodes"][3]["actions"] = [action("old-h")]
    robot.accept_order(order)
    run(robot, 5)
    update = update_from(order, 1, 2)  # the horizon (N3 with old-h) is replaced by an identical one

    assert robot.accept_order(update) is True


# --- S5: batteryEmpty whenever the battery is 0 -----------------------------------------------------------------


@BOTH
def test_battery_empty_on_arrival_at_the_last_node_is_reported(major):
    robot = Robot("robot_01", 20, 20, vda_major=major)
    robot.battery = 0.1  # exactly the 0.5 m to the last node
    robot.accept_order(make_order(points=((20, 20), (20.5, 20))))
    run(robot, 2)

    [error] = [e for e in robot.errors if e["errorType"] == "batteryEmpty"]
    assert error["errorLevel"] == "FATAL" and robot.battery == 0
    assert robot.accept_order(make_order(order_id="z", points=((20.5, 20), (21, 20)))) is False


@BOTH
def test_battery_empty_at_the_decision_point_is_reported_and_goes_when_charged(major):
    robot = Robot("robot_01", 20, 20, vda_major=major)
    order = horizon_order()
    for n in order["nodes"]:
        n["nodePosition"]["x"] += 20
        n["nodePosition"]["y"] += 20
    robot.battery = 0.4  # 2 m: exactly to N1, the decision point
    robot.accept_order(order)
    run(robot, 4)

    assert "batteryEmpty" in types(robot)
    robot.battery = 50.0
    robot.update(0.1)
    assert "batteryEmpty" not in types(robot)


# --- S6: a state for every order that arrives -------------------------------------------------------------------


def test_second_rejection_and_duplicate_change_the_event_signature_or_request_a_state():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="busy", points=((0, 0), (50, 0))))
    run(robot, 1)
    robot.handle_order_payload(json.dumps(make_order(order_id="X1", points=((0, 0), (1, 0)))).encode())
    before = robot.event_signature()
    robot.handle_order_payload(json.dumps(make_order(order_id="X2", points=((0, 0), (1, 0)))).encode())
    assert robot.event_signature() != before  # same errorType, other references

    robot.state_requested = False
    robot.handle_order_payload(json.dumps(make_order(order_id="busy", points=((0, 0), (50, 0)))).encode())
    assert robot.state_requested is True  # a duplicate is answered too


def test_step_publishes_a_state_for_a_received_duplicate_order():
    robot = Robot("robot_01")
    robot.accept_order(make_order(order_id="busy", points=((0, 0), (50, 0))))
    connection = connection_with(robot)
    published = []
    connection.publish_state = lambda: published.append(1)
    connection.inbox.put(
        (connection.order_topic, json.dumps(make_order(order_id="busy", points=((0, 0), (50, 0)))).encode())
    )

    sim_main.step([connection], 1, 1000)

    assert published == [1]


# --- S7: the tick clock starts again after a stall -----------------------------------------------------------------


def test_ticks_do_not_catch_up_in_a_burst_after_a_stall(monkeypatch):
    now, ran = [0.0], []

    def fake_step(connections, tick, ticks_per_publish):
        ran.append(now[0])
        if tick == 100:
            now[0] += 60  # the process was stopped for 60 s
        now[0] += 0.0005

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(sim_main, "step", fake_step)
    sim_main.tick_loop([], 10, lambda: now[0] < 75, clock=lambda: now[0], sleep=sleep)

    resumed = [t for t in ran if t >= 60]
    assert sum(1 for t in resumed if t < resumed[0] + 1.0) <= 11


# --- S8: factsheet advertises the enforced limits ----------------------------------------------------------------


@BOTH
def test_factsheet_advertises_the_array_limits(major):
    factsheet = Robot("robot_01", vda_major=major).factsheet_message()
    limits = factsheet["protocolLimits"]["maxArrayLens" if major == "v2" else "maximumArrayLengths"]

    assert limits["order.nodes"] == limits["order.edges"] == 300
    assert limits["node.actions"] == limits["edge.actions"] == 300
    assert limits["instantActions"] == 50
    assert not list(official(major, "factsheet").iter_errors(factsheet))


# --- S9: the state is serialised once ---------------------------------------------------------------------------


def test_publishing_a_state_serialises_it_once(monkeypatch):
    robot = Robot("robot_01")
    robot.accept_order(make_order())
    connection = connection_with(robot)
    sent = []
    connection._client = SimpleNamespace(is_connected=lambda: True, publish=lambda *a, **k: sent.append(a))
    calls = []
    real = json.dumps
    monkeypatch.setattr(json, "dumps", lambda *a, **k: calls.append(1) or real(*a, **k))

    connection.publish_state()

    assert len(calls) == 1 and len(sent) == 1
    assert json.loads(sent[0][1])["orderId"] == robot.order_id


# --- S10: a tiny 3.0 ellipse is rejected, not an exception -----------------------------------------------------


def test_tiny_or_huge_ellipse_does_not_overflow():
    for axes in (1e-300, 1e300):
        order = make_order(points=((0, 0), (3, 4)))
        order["nodes"][0]["nodePosition"]["allowedDeviationXY"] = {"a": axes, "b": axes, "theta": 1e300}
        robot = Robot("robot_01", 0.1, 0, vda_major="v3")

        assert robot.handle_order_payload(json.dumps(order).encode()) is (axes == 1e300)
        if axes == 1e-300:
            assert types(robot) == ["START_NODE_OUT_OF_RANGE"]


# --- S12: 3.0 names -----------------------------------------------------------------------------------------


@BOTH
def test_new_order_with_empty_battery_uses_the_versions_name(major):
    robot = Robot("robot_01", vda_major=major)
    robot.battery = 0

    assert robot.accept_order(make_order()) is False
    assert types(robot) == ["orderError" if major == "v2" else "MOBILE_ROBOT_NOT_AVAILABLE"]


# --- Suspected: stop() racing a rejoin; malformed siblings of a cancelOrder -------------------------------------


class Info:
    def wait_for_publish(self, timeout=None):
        pass


def test_stop_while_a_rejoin_just_finished_still_says_offline():
    connection = connection_with()
    published = []
    connection._client = SimpleNamespace(
        is_connected=lambda: True,
        publish=lambda topic_name, payload, **kw: published.append(json.loads(payload)) or Info(),
        disconnect=lambda: None,
        loop_stop=lambda: None,
    )
    connection._reconnect_at = 5.0  # away on purpose, and the reconnect helper has just finished
    connection._rejoin_ok = True
    connection._helper = threading.Thread(target=lambda: None)
    connection._helper.start()

    connection.stop()

    assert [m["connectionState"] for m in published] == ["OFFLINE"]


@BOTH
def test_a_malformed_sibling_does_not_drop_a_valid_cancel_order(major):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(points=((0, 0), (10, 0))))
    run(robot, 1)
    actions = [
        {"actionType": 5, "actionId": "bad"},
        {"actionType": "cancelOrder", "actionId": "c", "blockingType": "NONE"},
    ]

    robot.handle_instant_actions_payload(json.dumps({"actions": actions}).encode())

    assert robot.mission_status == "CANCELLED"


def test_failed_state_has_the_battery_empty_error_once():
    robot = Robot("robot_01", 20, 20)
    robot.battery = 0.3
    robot.accept_order(make_order(points=((20, 20), (25, 20))))
    run(robot, 5)

    assert robot.mission_status == FAILED
    assert types(robot).count("batteryEmpty") == 1
