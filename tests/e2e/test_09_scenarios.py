"""Scenario tests on the real stack (D-45, D-46): `actunode test` runs the five sample scenarios (each recorded
as a session), reports a failing scenario with exit code 1 and JUnit XML, and leaves the robots as it found
them."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from conftest import LOGIN, ROOT, SHARED, VDA, wait_for
from test_06_orders import wait_idle


def actunode_test(stack, tmp_path, *paths, junit=None) -> subprocess.CompletedProcess:
    command = [sys.executable, "-m", "actunode", "test", "--url", stack.http_base, "--vda-version", VDA]
    if LOGIN:
        token = tmp_path / "token"
        token.write_text(stack.secret("backend/api-token") + "\n")
        command += ["--token-file", str(token)]
    if SHARED:
        command += ["--ca-file", str(stack.ca_file)]
    if junit:
        command += ["--junit", str(junit)]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "cli")}
    result = subprocess.run([*command, *map(str, paths)], env=env, capture_output=True, text=True, timeout=600)
    print(result.stdout, result.stderr)
    return result


def test_the_sample_scenarios_pass_and_each_run_is_recorded(stack, tmp_path):
    junit = tmp_path / "junit.xml"
    result = actunode_test(stack, tmp_path, ROOT / "scenarios", junit=junit)
    assert result.returncode == 0, result.stdout
    assert "6 scenario(s): 6 passed, 0 failed, 0 could not run" in result.stdout
    root = ET.parse(junit).getroot()
    suite = root.find("testsuite")
    assert (suite.get("tests"), suite.get("failures"), suite.get("errors")) == ("6", "0", "0")
    # D-46: every run is a session in the lab, named after its file.
    recorded = [p.get("value") for p in root.iter("property") if p.get("name") == "actunode.session"]
    assert len(recorded) == 6
    sessions = {s["sessionId"] for s in stack.api.get("/sessions").json()}
    assert set(recorded) <= sessions
    assert any(name.endswith("_p1042_blocked_path") for name in recorded)


def test_a_failing_scenario_exits_1_and_cleans_up(stack, tmp_path):
    robot_id = "robot_02"
    wait_idle(stack, robot_id)
    scenario = tmp_path / "wrong_level.yaml"
    scenario.write_text(
        f"""name: pathBlocked is never FATAL
steps:
  - send_mission: {{robot: {robot_id}, destination: LOADING_DOCK_2, as: m}}
  - expect: {{robot: {robot_id}, order: m, status: MOVING, within: 15}}
  - inject: {{robot: {robot_id}, failure: BLOCKED_PATH}}
  - expect: {{robot: {robot_id}, error: {{type: pathBlocked, level: FATAL}}, within: 2}}
"""
    )
    junit = tmp_path / "junit.xml"
    result = actunode_test(stack, tmp_path, scenario, junit=junit)
    assert result.returncode == 1, result.stdout
    assert "pathBlocked is" in result.stdout and "(expected FATAL)" in result.stdout
    assert f"cleanup: cleared BLOCKED_PATH on {robot_id}" in result.stdout
    assert "cleanup: cancelled order-" in result.stdout
    assert ET.parse(junit).getroot().find("testsuite/testcase/failure") is not None
    # Left as found: no longer blocked, its order cancelled rather than still driving.
    wait_for(lambda: stack.status(robot_id) == "CANCELLED", 10, f"{robot_id} CANCELLED by cleanup")
    assert "pathBlocked" not in {e["errorType"] for e in stack.robots()[robot_id]["state"]["errors"]}
