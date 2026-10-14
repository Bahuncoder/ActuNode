"""The plan's demo question on the real stack (D-48): the example fleet manager drives robot_03 with its own login;
the blocked-path scenario passes when it cancels and fails when it ignores the block.

Runs after test_10: adding a login restarts the broker.
"""

import os
import subprocess
import sys

import pytest
from conftest import HOST, ROOT, SHARED, VDA, wait_for
from test_06_orders import wait_idle
from test_09_scenarios import actunode_test

EXAMPLE = ROOT / "examples" / "fleet_manager"


@pytest.fixture(scope="module")
def login(stack, tmp_path_factory):
    out = stack.compose("run", "--rm", "--no-deps", "mqtt-init", "add-master", "e2e_example")
    password_file = tmp_path_factory.mktemp("fm") / "password"
    password_file.write_text(out.split("password=")[1].split()[0])
    stack.compose("up", "-d", "--force-recreate", "mqtt-init", "mosquitto")
    wait_for(lambda: stack.api.get("/health").json()["mqtt"]["connected"], 60, "backend back on the broker")
    wait_for(stack.all_online, 60, "robots back online")
    return password_file


def fleet_manager(stack, password_file, policy: str) -> subprocess.Popen:
    command = [
        sys.executable, str(EXAMPLE / "fleet_manager.py"), "--host", HOST, "--port", str(stack.mqtt_port),
        "--user", "master@e2e_example", "--password-file", str(password_file), "--vda", VDA, "--policy", policy,
        "--max-seconds", "300",
    ]  # fmt: skip
    if SHARED:
        command += ["--ca-file", str(stack.ca_file)]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ)


def stop(process: subprocess.Popen) -> str:
    process.terminate()
    out, _ = process.communicate(timeout=10)
    print(out)
    return out


@pytest.mark.parametrize(("policy", "exit_code"), [("cancel", 0), ("ignore", 1)])
def test_the_blocked_path_scenario_tells_a_good_fleet_manager_from_a_bad_one(stack, login, tmp_path, policy, exit_code):
    # Start from a free robot: not one still finishing the previous fleet manager's order (the block could land
    # just as that leg ends, when there is no route left to block).
    if stack.status("robot_03") in ("ACCEPTED", "MOVING", "BLOCKED", "WAITING"):
        stack.post("/missions/robot_03/cancel", {"vda_version": VDA}, expect=202)
    wait_idle(stack, "robot_03")
    process = fleet_manager(stack, login, policy)
    try:
        result = actunode_test(stack, tmp_path, EXAMPLE / "blocked_path_reaction.yaml")
    finally:
        log = stop(process)
    assert result.returncode == exit_code, result.stdout
    assert "pathBlocked" in log  # the fleet manager saw the robot report it
    if policy == "cancel":
        assert "cancelOrder sent to robot_03" in log
    else:
        assert "none of:" in result.stdout  # it says which reactions it waited for
    # Either way the robot is left free: the block is cleared or already over.
    wait_for(lambda: stack.status("robot_03") != "BLOCKED", 10, "robot_03 not left blocked")
