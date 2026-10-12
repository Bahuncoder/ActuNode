"""Everything the simulator sends must pass the official VDA 5050 schemas of the version it speaks.

The schemas are the ones the backend vendors (backend/app/schemas), so both sides use one copy.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from simulator.robot import Robot
from simulator.tests.test_robot import make_order
from simulator.topics import topic

SCHEMAS = Path(__file__).resolve().parents[2] / "backend" / "app" / "schemas"
FOLDERS = {"v2": "vda5050-2.1.0", "v3": "vda5050-3.0.0"}


def official(major: str, name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / FOLDERS[major] / f"{name}.schema").read_text()))


def messages_in_every_state(major: str) -> list[tuple[str, str, dict]]:
    robot = Robot("robot_01", 1, 1, vda_major=major)
    out = [("IDLE", "state", robot.state_message())]
    robot.accept_order(make_order(points=((1, 1), (3, 5))))
    out.append(("ACCEPTED", "state", robot.state_message()))
    for _ in range(15):
        robot.update(0.1)
    out.append(("MOVING", "state", robot.state_message()))
    robot.block_path()
    out.append(("BLOCKED", "state", robot.state_message()))
    robot.clear_blocked_path()
    robot.battery = 0.0
    robot.update(0.1)
    out.append(("FAILED", "state", robot.state_message()))
    for connection in ("ONLINE", "OFFLINE", "CONNECTIONBROKEN"):
        out.append((connection, "connection", robot.connection_message(connection)))
    return out


@pytest.mark.parametrize("major", ["v2", "v3"])
def test_every_message_passes_the_official_schema(major):
    failures = []
    for label, kind, payload in messages_in_every_state(major):
        for error in official(major, kind).iter_errors(payload):
            failures.append(f"{label} {kind} /{'/'.join(map(str, error.absolute_path))}: {error.message}")
    assert not failures, "\n".join(failures)


def test_3_0_robot_uses_3_0_names():
    robot = Robot("robot_01", 1, 1, vda_major="v3")
    state = robot.state_message()

    assert state["version"] == "3.0.0"
    assert state["mobileRobotPosition"]["localized"] is True
    assert state["powerSupply"]["stateOfCharge"] == 100
    assert state["safetyState"]["activeEmergencyStop"] == "NONE"
    assert state["instantActionStates"] == []
    assert "agvPosition" not in state and "batteryState" not in state
    assert robot.connection_message("CONNECTIONBROKEN")["connectionState"] == "CONNECTION_BROKEN"


def test_2_1_robot_is_unchanged():
    state = Robot("robot_01", 1, 1).state_message()

    assert state["version"] == "2.1.0"
    assert state["agvPosition"]["positionInitialized"] is True
    assert "mobileRobotPosition" not in state


def test_topics_use_the_robots_major_version():
    assert topic("ActuNode", "robot_01", "state", "v3") == "uagv/v3/ActuNode/robot_01/state"


def test_unknown_version_is_refused():
    with pytest.raises(ValueError):
        Robot("robot_01", vda_major="v9")
