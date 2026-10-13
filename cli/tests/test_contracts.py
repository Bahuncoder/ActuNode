"""The runner reads the backend's answers; these shared fixtures are written by the backend's own tests
(backend/tests/test_contracts.py), so a change of shape there fails here instead of on a real stack (D-38)."""

import json
from pathlib import Path

from actunode.runner import Observation, pick_robot

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def test_robot_records_are_found_by_vda_version_as_the_api_spells_it():
    record = json.loads((CONTRACTS / "live_message_event.json").read_text())["robot"]
    major = record["vdaMajor"].removeprefix("v")
    assert pick_robot([record], record["robotId"], major) is record
    assert pick_robot([record], record["robotId"], "3" if major == "2" else "2") is None
    assert Observation.of(record).known
