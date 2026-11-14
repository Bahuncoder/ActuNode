"""A real ROS 2 robot stack on the real lab (D-51): Nav2 with a fake TurtleBot3 behind InOrbit's open-source
VDA 5050 connector, in the optional `ros2` profile. ActuNode sends it a mission and validates its traffic.

Opt-in (the image builds ROS 2 Humble, Nav2 and the connector: several minutes the first time):

    ACTUNODE_E2E_ROS2=1 tests/e2e/.venv/bin/pytest tests/e2e/test_13_ros2_robot.py -v
"""

import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest
from conftest import HOST, ROOT, SHARED, wait_for
from test_09_scenarios import actunode_test

pytestmark = pytest.mark.skipif(os.environ.get("ACTUNODE_E2E_ROS2") != "1", reason="set ACTUNODE_E2E_ROS2=1")

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
    # ActuNode sends headings (nodePosition.theta is optional in VDA 5050, but older connectors dropped such orders).
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
    assert ("schema", "/operatingMode") not in rules


# docs/CONFORMANCE_ROS2_CONNECTOR.md (D-52): the scenarios the connector fails. With the pinned commits, none. If
# this changes (a new commit), update the report, then this set.
KNOWN_FAILURES: set[str] = set()


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


# conformance/raw_checks.py: orders ActuNode's mission sender would never build. With the pinned commits, all pass
# (docs/CONFORMANCE_ROS2_CONNECTOR.md).
RAW_CHECKS = {
    "unreachable node is not reported reached",
    "unreachable node is reported as an error",
    "order on an unknown map is rejected",
    "an invalid order is rejected with an error, not ignored",
}
KNOWN_RAW_FAILURES: set[str] = set()


@pytest.mark.skipif(SHARED, reason="raw_checks.py speaks plain MQTT on the local port")
def test_the_raw_checks_still_hold(stack, ros2_robot, tmp_path):
    out = stack.compose("run", "--rm", "--no-deps", "mqtt-init", "add-master", "conformance", "ROS2")
    password = tmp_path / "conformance.pw"
    password.write_text(out.split("password=")[1].split()[0] + "\n")
    stack.compose("kill", "-s", "HUP", "mosquitto")  # load the new login (CONNECT_YOUR_ROBOT.md)
    time.sleep(2)
    command = [sys.executable, str(ROOT / "conformance" / "raw_checks.py"), "--password-file", str(password)]
    command += ["--host", HOST, "--port", str(stack.mqtt_port)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    print(result.stdout, result.stderr)
    verdicts = {}
    for line in result.stdout.splitlines():
        if line.startswith(("PASS  ", "FAIL  ")):
            name = line[6:].split(":")[0].split(" (")[0]
            verdicts[name] = line.startswith("PASS")
    assert set(verdicts) == RAW_CHECKS, result.stdout + result.stderr
    failed = {name for name, ok in verdicts.items() if not ok}
    assert failed == KNOWN_RAW_FAILURES, f"results changed: failed {sorted(failed)}; update the report"
