"""Helpers shared by the simulator tests."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from simulator.robot import ACCEPTED, MOVING, Robot

BOTH = pytest.mark.parametrize("major", ["v2", "v3"])


def make_order(serial="robot_01", order_id="order-1", points=((0, 0), (3, 4))):
    """Order through `points`; first node (where the robot starts) gets a pick, last a drop."""
    nodes = []
    for index, (x, y) in enumerate(points):
        actions = []
        if index == 0:
            actions = [{"actionId": "a-pick", "actionType": "pick", "blockingType": "HARD"}]
        elif index == len(points) - 1:
            actions = [{"actionId": "a-drop", "actionType": "drop", "blockingType": "HARD"}]
        nodes.append(
            {
                "nodeId": f"N{index}",
                "sequenceId": index * 2,
                "released": True,
                "nodePosition": {"x": x, "y": y, "mapId": "warehouse"},
                "actions": actions,
            }
        )
    edges = [
        {
            "edgeId": f"N{i - 1}->N{i}",
            "sequenceId": i * 2 - 1,
            "released": True,
            "startNodeId": f"N{i - 1}",
            "endNodeId": f"N{i}",
            "actions": [],
        }
        for i in range(1, len(points))
    ]
    return {"serialNumber": serial, "orderId": order_id, "orderUpdateId": 0, "nodes": nodes, "edges": edges}


def run_until_done(robot, dt=0.1, limit=10_000):
    for _ in range(limit):
        if robot.mission_status not in (ACCEPTED, MOVING):
            return
        robot.update(dt)
    raise AssertionError("mission never finished")


def types(robot):
    return [e["errorType"] for e in robot.errors]


def run(robot, seconds, dt=0.1):
    for _ in range(round(seconds / dt)):
        robot.update(dt)


def horizon_order(order_id="h-1", update_id=0, released=2, drop=True):
    """N0 (0,0) -> N1 (2,0) -> N2 (2,3) -> N3 (5,3); the first `released` nodes are the base."""
    points = [("N0", 0, 0), ("N1", 2, 0), ("N2", 2, 3), ("N3", 5, 3)]
    nodes = [
        {
            "nodeId": name,
            "sequenceId": i * 2,
            "released": i < released,
            "nodePosition": {"x": x, "y": y, "mapId": "warehouse"},
            "actions": [{"actionId": f"act-{name}", "actionType": "pick", "blockingType": "HARD"}]
            if drop and i == 1
            else [],
        }
        for i, (name, x, y) in enumerate(points)
    ]
    edges = [
        {
            "edgeId": f"{points[i - 1][0]}->{points[i][0]}",
            "sequenceId": i * 2 - 1,
            "released": i < released,
            "startNodeId": points[i - 1][0],
            "endNodeId": points[i][0],
            "actions": [],
        }
        for i in range(1, len(points))
    ]
    return {"serialNumber": "robot_01", "orderId": order_id, "orderUpdateId": update_id, "nodes": nodes, "edges": edges}


def update_from(order, first, released_to, update_id=1):
    """An update that starts at node index `first` of `order`, releasing up to index `released_to`."""
    update = copy.deepcopy(order)
    update["orderUpdateId"] = update_id
    update["nodes"] = update["nodes"][first:]
    update["edges"] = update["edges"][first:]
    for node in update["nodes"]:
        node["released"] = node["sequenceId"] <= released_to * 2
    for edge in update["edges"]:
        edge["released"] = edge["sequenceId"] <= released_to * 2 - 1
    return update


SCHEMAS = Path(__file__).resolve().parents[2] / "backend" / "app" / "schemas"
FOLDERS = {"v2": "vda5050-2.1.0", "v3": "vda5050-3.0.0"}


def official(major: str, name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / FOLDERS[major] / f"{name}.schema").read_text()))


def act(robot, action_type, action_id="i-1", **parameters):
    action = {"actionType": action_type, "actionId": action_id, "blockingType": "HARD"}
    if parameters:
        action["actionParameters"] = [{"key": k, "value": v} for k, v in parameters.items()]
    return robot.handle_instant_actions_payload(json.dumps({"actions": [action]}).encode())


def instants(robot):
    return robot.instant_action_states


def status(robot, action_id):
    return next(a["actionStatus"] for a in instants(robot) if a["actionId"] == action_id)


def driving_robot(major, order_id="o-1"):
    robot = Robot("robot_01", vda_major=major)
    robot.accept_order(make_order(order_id=order_id, points=((0, 0), (10, 0))))
    run(robot, 2)
    return robot


def send(robot, actions):
    return robot.handle_instant_actions_payload(json.dumps({"actions": actions}).encode())


class FakeConnection:
    def __init__(self, robot):
        self.robot = robot
        self.published = 0

    def apply_pending_messages(self):
        return False

    def update_link(self):
        pass

    def publish_malformed(self):
        pass

    def publish_state(self):
        self.published += 1


def snapshot(robot, *ignore):
    """A deep copy of everything the robot holds, minus the header counters (reading a message bumps them)
    and the attributes named in `ignore`: for "a rejected message changed nothing" checks."""
    skipped = {"_header_ids", *ignore}
    return copy.deepcopy({key: value for key, value in robot.__dict__.items() if key not in skipped})
