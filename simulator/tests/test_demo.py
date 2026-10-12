"""The offline playground in the README (`python3 main.py`) must finish: Week 3's start-node rule (D-35)
made it spin forever once, unnoticed."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_offline_demo_completes_the_mission():
    result = subprocess.run([sys.executable, "main.py"], cwd=ROOT, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert "COMPLETED" in result.stdout
