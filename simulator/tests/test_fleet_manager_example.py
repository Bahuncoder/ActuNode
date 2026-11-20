"""The example fleet manager (examples/fleet_manager) driving a real simulated Robot through simulator.__main__.step,
in simulated time, no broker: extending the base in time on a dense map, BATCHED_STATE + SPEED, a lost update."""

import json
import sys
from collections import defaultdict, deque
from pathlib import Path

import pytest

from simulator.__main__ import step
from simulator.robot import Robot

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples" / "fleet_manager"))

import fleet_manager  # noqa: E402

# base_extension.yaml's `never` match: stopped at the end of the base, asking for a new one.
MATCH = {"driving": False, "newBaseRequest": True, "actunode": {"missionStatus": "WAITING"}}
ROUTE = ["RECEIVING_DOOR_1", "LOADING_DOCK_1"]


def contains(pattern, value):
    if isinstance(pattern, dict):
        return isinstance(value, dict) and all(k in value and contains(p, value[k]) for k, p in pattern.items())
    return pattern == value and type(pattern) is type(value)


class Link:
    """A fake master-control link and a connection for step(): messages go to the robot at the next step."""

    def __init__(self, robot, vda, drop_update=None, **options):
        self.robot, self.queue, self.sent, self.dropped = robot, deque(), [], 0
        self.drop_update, self.states, self.rejections, self.t = drop_update, [], 0, 0
        self.fm = fleet_manager.FleetManager(self, vda, "ActuNode", "robot_03", ROUTE, "cancel", **options)
        self.fm.clock = lambda: self.t / 10

    def publish(self, topic, payload, qos=0):
        kind, message = topic.rsplit("/", 1)[1], json.loads(payload)
        self.sent.append((kind, message))
        if kind == "order" and message["orderUpdateId"] == self.drop_update and not self.dropped:
            self.dropped += 1  # a lost update (robot unresponsive, link down)
            return
        self.queue.append((kind, payload))

    def apply_pending_messages(self):
        while self.queue:
            kind, payload = self.queue.popleft()
            if kind == "order":
                if not self.robot.handle_order_payload(payload.encode()):
                    self.rejections.append(self.robot.errors[-1]["errorDescription"])
            else:
                self.robot.handle_instant_actions_payload(payload.encode())

    def update_link(self):
        pass

    def publish_malformed(self):
        pass

    def publish_factsheet(self):
        pass

    def publish_state(self):
        state = json.loads(self.robot.state_payload())
        self.states.append(state)
        self.fm.on_state(state)


def run(vda, seconds=150, batched=None, drop_update=None, **options):
    robot = Robot("robot_03", 3.2, 0.5, vda_major=f"v{vda}")
    robot.speed = 2.0
    if batched:
        robot.batched_every_s, robot.batch_timer = batched, 0
    link = Link(robot, vda, drop_update, **options)
    for tick in range(seconds * 10):
        link.t = tick
        step([link], tick, 10)
    return link


def orders(link):
    ids = defaultdict(list)
    for kind, message in link.sent:
        if kind == "order":
            ids[message["orderId"]].append(message["orderUpdateId"])
    return ids


def cancels(link):
    return [m for k, m in link.sent if k == "instantActions" and m["actions"][0]["actionType"] == "cancelOrder"]


def waits(link):
    return [s for s in link.states if contains(MATCH, s)]


@pytest.mark.parametrize("vda", ["2", "3"])
@pytest.mark.parametrize("spacing, base", [(2, 4), (0.5, 3)])
def test_early_extension_never_leaves_the_robot_waiting(vda, spacing, base):
    link = run(vda, spacing=spacing, base=base, extend="early")
    assert not waits(link) and not link.rejections
    assert link.fm.jobs >= 2
    assert all(v == list(range(len(v))) for v in orders(link).values())


@pytest.mark.parametrize("vda", ["2", "3"])
def test_late_extension_leaves_a_fast_robot_waiting(vda):
    assert waits(run(vda, spacing=2, base=4, extend="late"))


@pytest.mark.parametrize("vda", ["2", "3"])
def test_batched_state_with_speed_cancels_only_a_strict_fleet_manager(vda):
    assert not cancels(run(vda, batched=3, spacing=2, progress="any"))
    assert cancels(run(vda, batched=3, spacing=2, progress="strict"))


@pytest.mark.parametrize("vda", ["2", "3"])
def test_a_lost_update_is_sent_again_and_the_robot_still_finishes(vda):
    link = run(vda, spacing=2, base=4, extend="early", drop_update=1)
    assert link.dropped == 1 and not link.rejections
    assert link.fm.jobs >= 2  # the second job goes out only when the first order is done
    assert all(v == list(range(len(v))) for v in orders(link).values())
    assert max(len(v) for v in orders(link).values()) > 2
