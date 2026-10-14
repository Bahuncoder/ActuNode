"""actunode import on real traffic (D-49): capture the broker with mosquitto_sub, import, upload, validate."""

import os
import subprocess
import sys
import threading
import time

from conftest import ROOT, STATE_TOPIC
from test_06_orders import wait_idle
from test_07_sessions import NDJSON
from test_08_failures import inject


def test_a_capture_from_the_broker_becomes_a_session_the_lab_validates(stack, tmp_path):
    robot_id = "robot_01"
    wait_idle(stack, robot_id)
    # mosquitto_sub runs inside the broker container, on its plain listener, with the read-only login.
    command = ["exec", "-T", "mosquitto", "mosquitto_sub", "-h", "localhost", "-p", "1883", "-u", "tools"]
    command += ["-P", stack.tools_password, "-t", "uagv/#", "-F", "%U %t %p", "-W", "5"]
    captured: dict = {}

    def capture():
        try:
            captured["text"] = stack.compose(*command)
        except RuntimeError as error:  # -W ends with a timeout exit code once the time is up
            captured["text"] = str(error)

    thread = threading.Thread(target=capture)
    thread.start()
    time.sleep(1.5)
    assert inject(stack, robot_id, "INVALID_PAYLOAD", kind="not-json", count=1).status_code == 202
    thread.join(30)
    text = captured["text"]
    capture_file = tmp_path / "capture.txt"
    lines = [line for line in text.splitlines() if line.partition(" ")[0].replace(".", "").isdigit()]
    assert len(lines) > 5, text[:500]
    capture_file.write_text("\n".join(lines) + "\n")

    site = tmp_path / "site.jsonl"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "cli")}
    result = subprocess.run(
        [sys.executable, "-m", "actunode", "import", str(capture_file), "-o", str(site), "--name", "e2e_import"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout, result.stderr)
    assert result.returncode == 0, result.stdout
    assert f"ActuNode/{robot_id}" in result.stdout

    response = stack.api.post(
        "/sessions/upload", params={"name": "e2e_import"}, content=site.read_bytes(), headers=NDJSON, timeout=60
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["sessionId"]
    try:
        report = stack.api.post(f"/sessions/{session_id}/validate")
        assert report.status_code == 200, report.text
        report = report.json()
        assert report["checked"] > 5
        assert "invalid-json" in {issue["rule"] for issue in report["issues"]}, report["byRule"]
        states = [
            line
            for line in site.read_text().splitlines()
            if f'"topic":"{STATE_TOPIC.format(robot_id)}"' in line and '"payload":' in line
        ]
        assert states, "the robots' state messages are in the session"
    finally:
        stack.api.delete(f"/sessions/{session_id}")
