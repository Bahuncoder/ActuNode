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
# Positions kept and issues returned per message at most: the loop below is O(positions), and a flood of made-up
# robots (or a cluster of hundreds close together) must not make every message cost more (W8).
MAX_POSITIONS = 1000
MAX_ISSUES_PER_MESSAGE = 20


def state_position(state: dict) -> tuple[str, float, float, str] | None:
    """(json path, x, y, mapId) from a 2.x agvPosition or a 3.0 mobileRobotPosition, if well formed."""
    for key in ("agvPosition", "mobileRobotPosition"):
        position = state.get(key)
        if not isinstance(position, dict):
            continue
        x, y, map_id = position.get("x"), position.get("y"), position.get("mapId")
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in (x, y)) and isinstance(map_id, str):
            try:
                fx, fy = float(x), float(y)  # OverflowError for an integer beyond the float range
            except OverflowError:
                continue
            if math.isfinite(fx) and math.isfinite(fy):
                return f"/{key}", fx, fy, map_id
    return None


class ProximityMonitor:
    def __init__(
        self,
        min_distance: float = 1.0,
        stale_after: float = 3.0,
        now: Callable[[], float] = time.monotonic,
        max_robots: int = MAX_POSITIONS,
    ):
        self.max_robots = max_robots
        self.min_distance = min_distance
        self.stale_after = stale_after
        self._now = now
        self._positions: dict[str, tuple[float, float, str, float]] = {}  # robot -> x, y, mapId, seen at
        self._near: dict[tuple[str, str], float] = {}  # pair currently too close -> distance

    def observe(self, robot_id: str, state: dict) -> list[dict]:
        """Record a robot's position; return a `proximity` issue for each pair that just got too close."""
        if not isinstance(state, dict):
            return []
        position = state_position(state)
        if position is None:
            return []
        path, x, y, map_id = position
        now = self._now()
        # Forget robots silent for longer than stale_after: they cannot be near anyone, and this keeps
        # both memory and this loop proportional to the robots that are live.
        for stale in [r for r, p in self._positions.items() if now - p[3] > self.stale_after]:
            self.forget(stale)
        if robot_id not in self._positions and len(self._positions) >= self.max_robots:
            return []  # more live robots than the cap: the newcomers are not watched
        self._positions[robot_id] = (x, y, map_id, now)

        issues = []
        for other, (ox, oy, other_map, _seen_at) in list(self._positions.items()):
            if other == robot_id:
                continue
            pair = tuple(sorted((robot_id, other)))
            if other_map != map_id:
                self._near.pop(pair, None)  # on another map: no longer close, so re-report on return
                continue
            distance = math.hypot(x - ox, y - oy)
            if distance < self.min_distance:
                if pair not in self._near and len(issues) < MAX_ISSUES_PER_MESSAGE:
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
