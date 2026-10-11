import argparse

import pytest

from simulator.__main__ import MAX_ROBOTS, parking_spot, robot_count, step
from simulator.robot import Robot
from simulator.tests.test_robot import make_order


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


class FakeConnection:
    def __init__(self, robot):
        self.robot = robot
        self.published = 0

    def apply_pending_messages(self):
        return False

    def publish_state(self):
        self.published += 1


def test_step_publishes_on_node_traversal_between_periodic_ticks():
    robot = Robot("robot_01")
    robot.accept_order(make_order(points=((0.25, 0), (30, 0))))
    connection = FakeConnection(robot)
    step([connection], 0, 10)  # periodic: ACCEPTED -> MOVING
    step([connection], 1, 10)  # starts driving: event
    published = connection.published

    step([connection], 2, 10)  # driving along the edge, nothing new
    assert connection.published == published

    step([connection], 3, 10)  # reaches N0: lastNodeId changes
    assert connection.published == published + 1

    step([connection], 4, 10)
    assert connection.published == published + 1

    step([connection], 10, 10)  # periodic
    assert connection.published == published + 2
