"""conformance/raw_checks.py against a simulated robot (D-52): the simulator must pass every raw check, so the
checks themselves are known good before they are pointed at a real vehicle (test_13 runs them on the ROS 2 robot)."""

import subprocess
import sys
import time

import pytest
from conftest import HOST, ROOT, SHARED, VDA
from test_06_orders import wait_idle

ROBOT = "robot_03"
RAW_CHECKS = {
    "unreachable node is not reported reached",
    "unreachable node is reported as an error",
    "order on an unknown map is rejected",
    "an invalid order is rejected with an error, not ignored",
    "a single-node order is accepted and finished",
    "an empty order is rejected with an error, and the vehicle stays up",
    "the vehicle stops at the end of the base and continues when it is extended",
    "a rejected order's error does not block the next order",
}
# The simulated warehouse has no obstacles: it drives straight through the racks, so it cannot report that node as
# unreachable (the ROS 2 robot's Nav2 does).
NOT_APPLICABLE = {"unreachable node is reported as an error"}


@pytest.mark.skipif(SHARED or VDA != "2", reason="raw_checks.py speaks plain MQTT on the local port, VDA 5050 2.x")
def test_a_simulated_robot_passes_the_raw_checks(stack, tmp_path):
    wait_idle(stack, ROBOT)
    out = stack.compose("run", "--rm", "--no-deps", "mqtt-init", "add-master", "conformance", "ActuNode")
    password = tmp_path / "conformance.pw"
    password.write_text(out.split("password=")[1].split()[0] + "\n")
    stack.compose("kill", "-s", "HUP", "mosquitto")  # load the new login (CONNECT_YOUR_ROBOT.md)
    time.sleep(2)
    command = [sys.executable, str(ROOT / "conformance" / "raw_checks.py"), "--password-file", str(password)]
    command += ["--host", HOST, "--port", str(stack.mqtt_port), "--manufacturer", "ActuNode", "--serial", ROBOT]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    print(result.stdout, result.stderr)
    verdicts = {}
    for line in result.stdout.splitlines():
        if line.startswith(("PASS  ", "FAIL  ")):
            verdicts[line[6:].split(":")[0].split(" (")[0]] = line.startswith("PASS")
    assert set(verdicts) == RAW_CHECKS, result.stdout + result.stderr
    assert {name for name, ok in verdicts.items() if not ok} == NOT_APPLICABLE, result.stdout
