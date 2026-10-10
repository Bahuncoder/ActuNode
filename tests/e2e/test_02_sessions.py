"""Recording and replay on the real stack."""

import json
import time

from conftest import ORDER_TOPIC, STATE_TOPIC, wait_for


def read_session(stack, session_id: str) -> list[dict]:
    path = stack.sessions_dir / f"{session_id}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_record_a_mission_then_replay_it(stack):
    session_id = stack.post("/recording/start", {"name": "e2e"}, expect=201).json()["sessionId"]
    stack.post("/missions", {"robot_id": "robot_03", "destination": "CHARGING"}, expect=202)
    wait_for(lambda: stack.status("robot_03") == "COMPLETED", 30, "robot_03 COMPLETED")
    stack.post("/recording/stop", expect=200)

    records = read_session(stack, session_id)
    assert records[0]["type"] == "session" and records[-1]["type"] == "end"
    topics = {record["topic"] for record in records if record["type"] == "message"}
    assert ORDER_TOPIC.format("robot_03") in topics
    assert (stack.sessions_dir / f"{session_id}.jsonl").stat().st_uid == int(stack.env["ACTUNODE_UID"])

    # Replay is refused while the robots are live ...
    assert stack.post(f"/sessions/{session_id}/replay").status_code == 409

    # ... and works once the simulator is stopped.
    stack.compose("stop", "simulator")
    try:
        time.sleep(4)  # past the backend's 3 s live window
        with stack.watch(STATE_TOPIC.format("robot_03")) as replayed:
            stack.post(f"/sessions/{session_id}/replay", {"speed": 5}, expect=202)
            status = wait_for(lambda: replay_ended(stack), 30, "replay end")
        assert status["state"] == "finished"
        assert status["sent"] == status["total"]
        statuses = [payload["actunode"]["missionStatus"] for _, _, payload, _ in replayed if payload]
        assert "MOVING" in statuses and statuses[-1] == "COMPLETED"
    finally:
        stack.start_and_wait_live("start", "simulator")


def replay_ended(stack) -> dict | None:
    status = stack.api.get("/replay").json()["replay"]
    return status if status and status["state"] != "running" else None
