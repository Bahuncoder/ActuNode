"""The example fleet manager (examples/fleet_manager): each policy's reaction, repeated blocks, and that what it
sends is valid VDA 5050 for 2.1 and 3.0 (checked against the schemas the lab validates with)."""

import json
import sys
from pathlib import Path

import pytest
from jsonschema import validators

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples" / "fleet_manager"))

import fleet_manager  # noqa: E402

SCHEMAS = ROOT / "backend" / "app" / "schemas"
VERSIONS = [("2", "2.1.0", "agvPosition"), ("3", "3.0.0", "mobileRobotPosition")]
ROUTE = ["RECEIVING_DOOR_1", "LOADING_DOCK_1"]
BLOCKED = [{"errorType": "pathBlocked", "errorLevel": "WARNING"}]


class Broker:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic.rsplit("/", 1)[1], json.loads(payload)))

    def kinds(self):
        return [
            message["actions"][0]["actionType"] if kind == "instantActions" else kind for kind, message in self.sent
        ]


def manager(policy, vda="2"):
    broker = Broker()
    return fleet_manager.FleetManager(broker, vda, "ActuNode", "robot_03", ROUTE, policy), broker


def idle(vda="2", **extra):
    key = "agvPosition" if vda == "2" else "mobileRobotPosition"
    position = {"x": 5.0, "y": 6.0, "theta": 0, "mapId": "warehouse"}
    return {"orderId": "", "nodeStates": [], "edgeStates": [], "driving": False, "errors": [], key: position, **extra}


def blocked(fm, vda="2"):
    return idle(vda, orderId=fm.order_id, nodeStates=[{"nodeId": "x"}], errors=BLOCKED)


def clear(fm, vda="2", **extra):
    return idle(vda, orderId=fm.order_id, nodeStates=[{"nodeId": "x"}], **extra)


def check(version, kind, message):
    schema = json.loads((SCHEMAS / f"vda5050-{version}" / f"{kind}.schema").read_text())
    return [e.message for e in validators.validator_for(schema)(schema).iter_errors(message)]


def test_cancel_sends_cancel_order_and_the_next_job_goes_out():
    fm, broker = manager("cancel")
    fm.on_state(idle())
    fm.on_state(blocked(fm))
    assert broker.kinds() == ["order", "cancelOrder"]
    fm.on_state(idle(orderId=fm.order_id))  # the robot dropped the order (it keeps the order id)
    assert broker.kinds() == ["order", "cancelOrder", "order"]


def test_reroute_cancels_then_sends_the_same_job_via_a_detour():
    fm, broker = manager("reroute")
    fm.on_state(idle())
    destination = fm.destination
    fm.on_state(blocked(fm))
    assert broker.kinds() == ["order", "cancelOrder"]
    fm.on_state(idle(orderId=fm.order_id))
    order = broker.sent[-1][1]
    assert [n["nodeId"] for n in order["nodes"]] == ["start", "detour", destination]


def test_escalate_pauses_and_resumes_when_the_aisle_is_clear():
    fm, broker = manager("escalate")
    fm.on_state(idle())
    fm.on_state(blocked(fm))
    fm.on_state(blocked(fm))  # still blocked: not paused twice
    assert broker.kinds() == ["order", "startPause"]
    fm.on_state(clear(fm, paused=True))
    assert broker.kinds() == ["order", "startPause", "stopPause"]


def test_ignore_sends_nothing_after_the_first_order():
    fm, broker = manager("ignore")
    fm.on_state(idle())
    fm.on_state(blocked(fm))
    fm.on_state(blocked(fm))
    assert broker.kinds() == ["order"]


@pytest.mark.parametrize("policy", ["cancel", "escalate"])
def test_a_second_block_on_the_same_order_gets_a_reaction_again(policy):
    fm, broker = manager(policy)
    fm.on_state(idle())
    fm.on_state(blocked(fm))
    fm.on_state(clear(fm, paused=True))  # the block ends, the order goes on
    count = len(broker.sent)
    fm.on_state(blocked(fm))
    assert len(broker.sent) == count + 1


def test_a_state_without_a_position_sends_no_order_until_there_is_one():
    fm, broker = manager("cancel")
    for position in (None, {}, {"x": None, "y": 1}, {"x": True, "y": 1}, {"x": "1", "y": 2}):
        state = idle()
        state.pop("agvPosition")
        if position is not None:
            state["agvPosition"] = position
        fm.on_state(state)
    assert broker.sent == []
    fm.on_state(idle())
    assert broker.kinds() == ["order"]
    assert fm.jobs == 1 and fm.next_stop == 1  # the skipped states did not use up a stop of the route


@pytest.mark.parametrize(("vda", "version", "key"), VERSIONS)
@pytest.mark.parametrize("policy", fleet_manager.POLICIES)
def test_everything_it_sends_is_valid_vda_5050(policy, vda, version, key):
    fm, broker = manager(policy, vda)
    fm.on_state(idle(vda))
    fm.on_state(blocked(fm, vda))
    fm.on_state(clear(fm, vda, paused=True))
    fm.on_state(idle(vda, orderId=fm.order_id))
    fm.on_state(idle(vda, orderId=fm.order_id))
    assert broker.sent
    for kind, message in broker.sent:
        assert check(version, kind, message) == [], (kind, message)


# --- dense map, base and extension habits (D-68) ---


def dense(vda="2", **options):
    broker = Broker()
    fm = fleet_manager.FleetManager(broker, vda, "ActuNode", "robot_03", ROUTE, "cancel", **options)
    fm.on_state(idle(vda))
    return fm, broker


def driving(fm, last, vda="2", released=None, **extra):
    """A state at sequence `last`; the first `released` (default: the base) nodes of the order are released."""
    released = fm.base if released is None else released
    nodes = [{"sequenceId": 2 * i, "released": i < released} for i in range(len(fm.stops)) if 2 * i > last]
    return idle(vda, orderId=fm.order_id, nodeStates=nodes, lastNodeSequenceId=last, driving=True, **extra)


def test_spacing_puts_nodes_at_most_that_far_apart_with_unique_ids():
    stops = fleet_manager.interpolate([("a", 0, 0), ("m", 5, 0), ("b", 5, 3)], 2)
    assert stops[0][0] == "a" and stops[-1][0] == "b" and ("m", 5, 0) in stops
    assert len({s[0] for s in stops}) == len(stops)
    assert all(abs(p[1] - q[1]) + abs(p[2] - q[2]) <= 2 + 1e-9 for p, q in zip(stops, stops[1:], strict=False))
    assert fleet_manager.interpolate([("a", 0, 0), ("b", 5, 0)], 0) == [("a", 0, 0), ("b", 5, 0)]


@pytest.mark.parametrize("vda", ["2", "3"])
def test_base_releases_only_the_first_nodes_and_edges(vda):
    fm, broker = dense(vda, spacing=2, base=4)
    order = broker.sent[0][1]
    assert [n["sequenceId"] for n in order["nodes"]] == [2 * i for i in range(len(order["nodes"]))]
    assert [n["released"] for n in order["nodes"]][:5] == [True] * 4 + [False]
    assert sum(n["released"] for n in order["nodes"]) == 4
    assert sum(e["released"] for e in order["edges"]) == 3
    assert [e["sequenceId"] for e in order["edges"]] == [2 * i + 1 for i in range(len(order["edges"]))]


def test_without_base_the_whole_order_is_released():
    _, broker = dense(spacing=2)
    assert all(n["released"] for n in broker.sent[0][1]["nodes"])


def test_early_extends_while_the_robot_still_has_nodes_ahead_and_never_twice():
    fm, broker = dense(spacing=2, base=4, extend="early")
    fm.on_state(driving(fm, 0))  # 3 ahead: not yet
    assert len(broker.sent) == 1
    fm.on_state(driving(fm, 2))  # 2 ahead: extend
    update = broker.sent[1][1]
    assert update["orderId"] == fm.order_id and update["orderUpdateId"] == 1
    assert update["nodes"][0]["sequenceId"] == 6 and update["nodes"][0]["released"]
    assert [n["released"] for n in update["nodes"]] == [True] * 5  # the 8-node order is now fully released
    assert update["edges"][0]["startNodeId"] == update["nodes"][0]["nodeId"]
    fm.on_state(driving(fm, 2))  # the same state again: no second release
    assert len(broker.sent) == 2
    fm.on_state(driving(fm, 4, released=8))  # the robot shows the longer base: nothing more to release
    assert len(broker.sent) == 2


def test_a_lost_or_rejected_update_is_sent_again_after_3_seconds_with_a_new_update_id():
    now = [0.0]
    fm, broker = dense(spacing=2, base=4, extend="early")
    fm.clock = lambda: now[0]
    fm.on_state(driving(fm, 2))
    assert [m["orderUpdateId"] for k, m in broker.sent if k == "order"] == [0, 1]
    now[0] = 2.9
    fm.on_state(driving(fm, 4))  # still the old base, not 3 s yet
    assert len(broker.sent) == 2
    now[0] = 3.0
    fm.on_state(driving(fm, 6))  # at the end of the old base now: the stitch is the robot's last released node
    update = broker.sent[2][1]
    assert update["orderUpdateId"] == 2 and update["nodes"][0]["sequenceId"] == 6
    fm.on_state(driving(fm, 6, released=8))
    assert len(broker.sent) == 3


def test_late_waits_until_the_robot_has_stopped_at_the_end_of_the_base():
    fm, broker = dense(spacing=2, base=4, extend="late")
    for last in (0, 2, 4):
        fm.on_state(driving(fm, last))
    fm.on_state(driving(fm, 6))  # at the last released node but still driving
    assert len(broker.sent) == 1
    stopped = driving(fm, 6)
    stopped["driving"] = False
    fm.on_state(stopped)
    assert broker.sent[1][1]["orderUpdateId"] == 1


def test_an_update_keeps_the_rest_as_horizon():
    fm = fleet_manager.FleetManager(Broker(), "2", "ActuNode", "robot_03", ROUTE, "cancel", spacing=2, base=4)
    fm.stops = fleet_manager.interpolate([("a", 0, 0), ("b", 20, 0)], 2)  # 11 nodes
    fm.order_id = "o"
    fm.extend_base(4)
    nodes = fm.client.sent[0][1]["nodes"]
    assert [n["released"] for n in nodes] == [True] * 5 + [False] * 3 and nodes[0]["sequenceId"] == 6


def test_extension_stops_when_the_whole_order_is_released():
    assert not fleet_manager.extension_due("early", 4, 5, 5, {"lastNodeSequenceId": 8})
    assert not fleet_manager.extension_due("early", 0, 4, 9, {"lastNodeSequenceId": 6})


@pytest.mark.parametrize("vda", ["2", "3"])
def test_strict_cancels_once_when_several_nodes_pass_between_two_states(vda):
    fm, broker = dense(vda, spacing=2, progress="strict")
    fm.on_state(driving(fm, 0, vda))
    fm.on_state(driving(fm, 2, vda))  # one node: fine
    assert broker.kinds() == ["order"]
    fm.on_state(driving(fm, 8, vda))
    fm.on_state(driving(fm, 14, vda))
    assert broker.kinds() == ["order", "cancelOrder"]


def test_any_accepts_several_nodes_at_once():
    fm, broker = dense(spacing=2, progress="any")
    fm.on_state(driving(fm, 0))
    fm.on_state(driving(fm, 8))
    assert broker.kinds() == ["order"]


def test_a_rejected_order_update_is_logged(caplog):
    fm, _ = dense(spacing=2, base=4)
    caplog.set_level("ERROR")
    fm.on_state(driving(fm, 0, errors=[{"errorType": "orderUpdateError", "errorDescription": "bad"}]))
    assert "orderUpdateError" in caplog.text
