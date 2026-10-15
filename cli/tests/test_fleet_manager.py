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
