"""Near-collision detection: report when two live robots come closer than a minimum distance.

ActuNode only observes and reports (evidence for the integration under test); it never steers robots.
Keeping robots apart is the fleet manager's job (see docs/DECISIONS.md, D-22).
"""

import math
import time
from collections.abc import Callable

# A pair is reported once when it gets closer than min_distance, and re-armed only after moving
# beyond min_distance * REARM, so robots hovering near the limit do not flood the log.
REARM = 1.2


def _position(state: dict) -> tuple[str, float, float, str] | None:
    """(json path, x, y, mapId) from a 2.x agvPosition or a 3.0 mobileRobotPosition, if well formed."""
    for key in ("agvPosition", "mobileRobotPosition"):
        position = state.get(key)
        if not isinstance(position, dict):
            continue
        x, y, map_id = position.get("x"), position.get("y"), position.get("mapId")
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in (x, y)) and isinstance(map_id, str):
            if math.isfinite(x) and math.isfinite(y):
                return f"/{key}", float(x), float(y), map_id
    return None


class ProximityMonitor:
    def __init__(
        self,
        min_distance: float = 1.0,
        stale_after: float = 3.0,
        now: Callable[[], float] = time.monotonic,
    ):
        self.min_distance = min_distance
        self.stale_after = stale_after
        self._now = now
        self._positions: dict[str, tuple[float, float, str, float]] = {}  # robot -> x, y, mapId, seen at
        self._near: dict[tuple[str, str], float] = {}  # pair currently too close -> distance

    def observe(self, robot_id: str, state: dict) -> list[dict]:
        """Record a robot's position; return a `proximity` issue for each pair that just got too close."""
        if not isinstance(state, dict):
            return []
        position = _position(state)
        if position is None:
            return []
        path, x, y, map_id = position
        now = self._now()
        self._positions[robot_id] = (x, y, map_id, now)

        issues = []
        for other, (ox, oy, other_map, seen_at) in list(self._positions.items()):
            if other == robot_id or other_map != map_id or now - seen_at > self.stale_after:
                continue
            pair = tuple(sorted((robot_id, other)))
            distance = math.hypot(x - ox, y - oy)
            if distance < self.min_distance:
                if pair not in self._near:
                    issues.append(
                        {
                            "severity": "warning",
                            "rule": "proximity",
                            "message": f"{robot_id} within {distance:.1f} m of {other} "
                            f"(minimum {self.min_distance:g} m) on {map_id}",
                            "path": path,
                        }
                    )
                self._near[pair] = distance
            elif distance > self.min_distance * REARM:
                self._near.pop(pair, None)
            elif pair in self._near:
                self._near[pair] = distance
        return issues

    def forget(self, robot_id: str) -> None:
        """The robot left (offline, connection broken): its last position no longer counts."""
        self._positions.pop(robot_id, None)
        for pair in [p for p in self._near if robot_id in p]:
            del self._near[pair]

    def active_pairs(self) -> list[dict]:
        """Pairs currently too close, ignoring robots that went silent."""
        now = self._now()
        live = {r for r, (*_, seen_at) in self._positions.items() if now - seen_at <= self.stale_after}
        return [
            {"robots": list(pair), "distance": round(distance, 2)}
            for pair, distance in sorted(self._near.items())
            if pair[0] in live and pair[1] in live
        ]
