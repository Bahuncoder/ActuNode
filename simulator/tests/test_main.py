import argparse

import pytest

from simulator.__main__ import MAX_ROBOTS, parking_spot, robot_count


def test_ten_robots_park_apart_inside_charging_area():
    spots = [parking_spot(i) for i in range(10)]

    assert len(set(spots)) == 10
    assert all(0 < x < 12 and 0 < y < 4 for x, y in spots)
    # At least 2 m between any two robots, so markers and labels do not overlap.
    for i, (x1, y1) in enumerate(spots):
        for x2, y2 in spots[i + 1 :]:
            assert ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 >= 2.0


@pytest.mark.parametrize("value", ["0", "-1", str(MAX_ROBOTS + 1)])
def test_robot_count_is_bounded(value):
    with pytest.raises(argparse.ArgumentTypeError):
        robot_count(value)


def test_robot_count_accepts_valid_values():
    assert robot_count("10") == 10
