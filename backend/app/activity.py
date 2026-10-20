"""How long the lab has been idle, for the hosted control plane to stop idle labs (D-61)."""

import time


class Activity:
    def __init__(self) -> None:
        self._last = time.monotonic()

    def touch(self) -> None:
        self._last = time.monotonic()

    def idle_seconds(self, live_clients: int) -> float:
        """0 while someone has the live feed open, else the time since the last touch."""
        return 0.0 if live_clients > 0 else time.monotonic() - self._last


activity = Activity()
