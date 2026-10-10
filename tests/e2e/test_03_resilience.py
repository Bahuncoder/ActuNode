"""Failure of processes and connections. Runs last: it restarts services."""

import json
import time

from conftest import CONNECTION_BROKEN, ROBOTS, VDA, wait_for


def connections(stack) -> set[str]:
    return {(stack.robots().get(r) or {}).get("connection") for r in ROBOTS}


def test_killed_simulator_is_reported_as_connection_broken(stack):
    assert stack.all_online(), "precondition: robots must be live before the kill"
    stack.compose("kill", "simulator")  # SIGKILL: no goodbye, only the MQTT last will
    try:
        wait_for(lambda: connections(stack) == {CONNECTION_BROKEN}, 30, f"last will {CONNECTION_BROKEN} for all robots")
    finally:
        stack.start_and_wait_live("start", "simulator")


def test_robots_and_backend_recover_after_a_broker_restart(stack):
    before = {r: stack.robots()[r]["lastStateAt"] for r in ROBOTS}
    stack.compose("restart", "mosquitto")

    wait_for(lambda: stack.api.get("/health").json()["mqtt"]["connected"], 40, "backend reconnected")
    wait_for(stack.all_online, 40, "robots ONLINE again")
    wait_for(
        lambda: all(stack.robots()[r]["lastStateAt"] > before[r] for r in ROBOTS), 20, "fresh state from every robot"
    )
    stack.post("/missions", {"vda_version": VDA, "robot_id": "robot_01", "destination": "STORAGE_B04"}, expect=202)
    wait_for(lambda: stack.status("robot_01") == "MOVING", 10, "missions work after reconnect")


def test_backend_stop_closes_an_open_recording(stack):
    """Reboot order: broker first, then backend. The recording must still get its end line."""
    session_id = stack.post("/recording/start", {"name": "shutdown"}, expect=201).json()["sessionId"]
    time.sleep(2)
    stack.compose("stop", "mosquitto")
    try:
        started = time.monotonic()
        stack.compose("stop", "backend")
        took = time.monotonic() - started

        last = json.loads((stack.sessions_dir / f"{session_id}.jsonl").read_text().splitlines()[-1])
        assert last["type"] == "end"
        assert took < 8, f"backend took {took:.1f} s to stop"
    finally:
        stack.start_and_wait_live("up", "-d", "--wait", "--wait-timeout", "120")
