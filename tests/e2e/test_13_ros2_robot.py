"""A real ROS 2 robot stack on the real lab (D-51): Nav2 with a fake TurtleBot3 behind InOrbit's open-source
VDA 5050 connector, in the optional `ros2` profile. ActuNode sends it a mission and validates its traffic.

Opt-in (the image builds ROS 2 Humble, Nav2 and the connector: several minutes the first time):

    ACTUNODE_E2E_ROS2=1 tests/e2e/.venv/bin/pytest tests/e2e/test_13_ros2_robot.py -v
"""

import math
import os
import time
import xml.etree.ElementTree as ET

import pytest
from conftest import ROOT, wait_for
from test_09_scenarios import actunode_test

pytestmark = pytest.mark.skipif(os.environ.get("ACTUNODE_E2E_ROS2") != "1", reason="set ACTUNODE_E2E_ROS2=1")

# ACTUNODE_ROS2_PATCHES=1 builds the robot with ros2/patches/ (the fixes we propose upstream); the default is the
# connector and adapter exactly as pinned, as measured in docs/CONFORMANCE_ROS2_CONNECTOR.md.
PATCHED = os.environ.get("ACTUNODE_ROS2_PATCHES") == "1"
KEY = "v2/ROS2/nav2_01"
STORAGE_A17 = (14.0, 18.0)


def robot(stack) -> dict | None:
    return next((r for r in stack.api.get("/robots").json() if r["key"] == KEY), None)


def position(stack) -> tuple[float, float]:
    state = robot(stack)["state"]
    return state["agvPosition"]["x"], state["agvPosition"]["y"]


@pytest.fixture(scope="module")
def ros2_robot(stack):
    stack.compose("--profile", "ros2", "up", "-d", "--build", "ros2-robot", timeout=1800)
    try:
        wait_for(lambda: (robot(stack) or {}).get("connection") == "ONLINE", 180, "ROS 2 robot ONLINE")
        wait_for(lambda: (robot(stack) or {}).get("state") is not None, 60, "ROS 2 robot state")
        yield
    finally:
        stack.compose("--profile", "ros2", "stop", "ros2-robot")


def test_the_ros2_robot_logs_in_like_a_real_robot_over_tls(stack, ros2_robot):
    record = robot(stack)
    assert record["manufacturer"] == "ROS2" and record["vdaMajor"] == "v2"
    assert record["state"]["agvPosition"]["mapId"] == "map"  # the connector's adapter always says "map"


def test_actunode_sends_it_a_mission_and_it_drives_around_the_racks(stack, ros2_robot):
    start = position(stack)
    sent = stack.post(
        "/missions",
        {
            "robot_id": "nav2_01",
            "manufacturer": "ROS2",
            "vda_version": "2",
            "destination": "STORAGE_A17",
            "theta": 1.57,
        },
        expect=202,
    ).json()
    # The connector drops orders without nodePosition.theta (optional in VDA 5050): ActuNode sends headings.
    assert all("theta" in node["nodePosition"] for node in sent["order"]["nodes"])

    def arrived() -> bool:
        state = robot(stack)["state"]
        x, y = position(stack)
        # Near the node *and* reporting it reached: the connector reports the node a moment after Nav2 arrives.
        at_node = state.get("lastNodeId") == "STORAGE_A17"
        return state.get("orderId") == sent["order_id"] and at_node and math.dist((x, y), STORAGE_A17) < 0.6

    wait_for(arrived, 120, "ROS 2 robot at STORAGE_A17, node reported")
    assert math.dist(start, position(stack)) > 5  # it really drove (the connector reports nodes reached on failure)


def test_its_traffic_is_validated(stack, ros2_robot):
    time.sleep(2)
    messages = [m for m in stack.api.get("/messages").json() if f"/{KEY.split('/', 1)[1]}/" in m["topic"]]
    assert messages, "no messages from the ROS 2 robot in the inspector"
    states = [m for m in messages if m["topic"].endswith("/state")]
    assert states
    rules = {(i["rule"], i["path"]) for m in states for i in m["issues"]}
    if PATCHED:
        assert ("schema", "/operatingMode") not in rules
    else:
        # Known deviation, reported in the Week 14 conformance report: operatingMode "" in every state.
        assert ("schema", "/operatingMode") in rules


# docs/CONFORMANCE_ROS2_CONNECTOR.md (D-52): the scenarios the connector fails. If this changes (a connector fix, a
# new commit), update the report and the upstream drafts, then this set.
# With ros2/patches/ applied, all pass.
KNOWN_FAILURES = set() if PATCHED else {"02", "04", "05", "06", "08"}


def test_the_conformance_report_still_holds(stack, ros2_robot, tmp_path):
    junit = tmp_path / "conformance.xml"
    actunode_test(stack, tmp_path, ROOT / "conformance" / "vda5050-2", junit=junit)
    passed = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        passed[case.get("name")[:2]] = case.find("failure") is None and case.find("error") is None
    assert sorted(passed) == [f"{n:02d}" for n in range(1, 10)]
    failed = {number for number, ok in passed.items() if not ok}
    assert failed == KNOWN_FAILURES, (
        f"results changed: failed {sorted(failed)}; update docs/CONFORMANCE_ROS2_CONNECTOR.md"
    )
