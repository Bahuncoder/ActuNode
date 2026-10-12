import argparse
import importlib.util
import math
from pathlib import Path

import pytest

from simulator.__main__ import MAX_ROBOTS, parking_spot, robot_count, step
from simulator.robot import CHARGING_AREA, PARKING_AREA, Robot
from simulator.tests.helpers import FakeConnection, make_order

# The map lives in backend/app/warehouse.py (single source, D-37); these tests read it directly so the
# simulator's parking layout cannot drift from the map the backend serves and the UI draws.
WAREHOUSE_PY = Path(__file__).resolve().parents[2] / "backend" / "app" / "warehouse.py"


def _backend_warehouse():
    spec = importlib.util.spec_from_file_location("backend_warehouse", WAREHOUSE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WAREHOUSE = _backend_warehouse()
ZONES = {zone["id"]: (zone["x"], zone["y"], zone["x"] + zone["w"], zone["y"] + zone["h"]) for zone in WAREHOUSE.ZONES}
OTHER_ZONES = [area for zone_id, area in ZONES.items() if zone_id not in ("charging", "parking")]


def _spots():
    return [parking_spot(i) for i in range(MAX_ROBOTS)]


def _inside(spot, area, margin=0.5):
    x_min, y_min, x_max, y_max = area
    return x_min + margin <= spot[0] <= x_max - margin and y_min + margin <= spot[1] <= y_max - margin


def test_parking_spots_are_distinct_and_deterministic():
    assert len(set(_spots())) == MAX_ROBOTS
    assert _spots() == _spots()


def test_parked_robots_never_trigger_the_proximity_warning():
    spots = _spots()
    for i, (x1, y1) in enumerate(spots):
        for x2, y2 in spots[i + 1 :]:
            assert math.hypot(x1 - x2, y1 - y2) >= 1.3


def test_parking_spots_keep_clear_of_named_locations():
    for spot in _spots():
        for name, location in WAREHOUSE.LOCATIONS.items():
            assert math.hypot(spot[0] - location["x"], spot[1] - location["y"]) >= 1.5, name


def test_parking_spots_fill_charging_area_first_then_parking_zone():
    zones = [
        "charging" if _inside(spot, CHARGING_AREA) else "parking" if _inside(spot, PARKING_AREA) else "elsewhere"
        for spot in _spots()
    ]
    assert "elsewhere" not in zones
    charging = zones.count("charging")
    assert zones == ["charging"] * charging + ["parking"] * (MAX_ROBOTS - charging)
    assert charging >= 3  # the e2e stack runs 3 robots and they must be able to charge
    for spot in _spots():
        for x_min, y_min, x_max, y_max in OTHER_ZONES:
            assert not (x_min <= spot[0] <= x_max and y_min <= spot[1] <= y_max)
        for rack in WAREHOUSE.RACKS:
            assert not (rack["x"] <= spot[0] <= rack["x"] + rack["w"] and rack["y"] <= spot[1] <= rack["y"] + rack["h"])


def test_charging_and_parking_areas_match_the_backend_map():
    assert CHARGING_AREA == ZONES["charging"]
    assert PARKING_AREA == ZONES["parking"]


@pytest.mark.parametrize("value", ["0", "-1", str(MAX_ROBOTS + 1)])
def test_robot_count_is_bounded(value):
    with pytest.raises(argparse.ArgumentTypeError):
        robot_count(value)


def test_robot_count_accepts_valid_values():
    assert robot_count("10") == 10


def test_step_publishes_on_node_traversal_between_periodic_ticks():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0, 0), (0.25, 0), (30, 0))))
    connection = FakeConnection(robot)
    step([connection], 0, 10)  # periodic: ACCEPTED -> MOVING
    step([connection], 1, 10)  # starts driving: event
    published = connection.published

    step([connection], 2, 10)  # driving along the edge, nothing new
    assert connection.published == published

    step([connection], 3, 10)  # reaches N1: lastNodeId changes
    assert connection.published == published + 1

    step([connection], 4, 10)
    assert connection.published == published + 1

    step([connection], 10, 10)  # periodic
    assert connection.published == published + 2
