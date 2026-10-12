"""Run simulated AMRs that publish VDA 5050 state over MQTT.

python -m simulator --robots 3
"""

import argparse
import logging
import os
import signal
import time
from pathlib import Path

from simulator.publisher import RobotConnection
from simulator.robot import VDA_VERSIONS, Robot

# Robots park first in the charging area (3 rows x 7 columns, 1.35 m apart), then in the PARKING zone
# (5 staggered rows x 6 columns). Every spot is >= 0.5 m inside its zone, >= 1.3 m from every other spot
# (above the proximity re-arm distance 1.2 m, D-22) and >= 1.5 m from every named location, so a robot
# sent to CHARGING never stops on a parked one. Robots in PARKING do not charge (D-33): that is intended.
CHARGING_SPOTS = [(round(0.5 + 1.35 * column, 3), y) for y in (0.5, 2.0, 3.5) for column in range(7)]
PARKING_SPOTS = [
    (round(0.5 + 1.35 * column + (0.675 if row % 2 else 0.0), 3), round(5.5 + 1.125 * row, 3))
    for row in range(5)
    for column in range(6)
]
PARKING_ORDER = CHARGING_SPOTS + PARKING_SPOTS
MAX_ROBOTS = 50

# Physics step. State is published every --interval and on every state event.
TICK_S = 0.1


def parking_spot(index: int) -> tuple[float, float]:
    return PARKING_ORDER[index]


def robot_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= MAX_ROBOTS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_ROBOTS}")
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="simulator", description="ActuNode AMR simulator")
    parser.add_argument("--robots", type=robot_count, default=os.getenv("ACTUNODE_SIM_ROBOTS", "3"))
    parser.add_argument("--host", default=os.getenv("ACTUNODE_MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ACTUNODE_MQTT_PORT", "1883")))
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between state messages")
    parser.add_argument(
        "--vda-version",
        choices=["2", "3"],
        default=os.getenv("ACTUNODE_VDA_VERSION", "2"),
        help="VDA 5050 major version the robots speak (2 = 2.1.0, 3 = 3.0.0)",
    )
    return parser.parse_args()


def _robot_password() -> str | None:
    """Shared password of the simulated robots (ACTUNODE_MQTT_PASSWORD_FILE), or None to connect
    anonymously to a development broker."""
    path = os.getenv("ACTUNODE_MQTT_PASSWORD_FILE")
    return Path(path).read_text().strip() if path else None


def step(connections, tick: int, ticks_per_publish: int) -> None:
    """One physics tick for every robot. State goes out periodically and, at most once per tick,
    on any VDA 5050 state event (see Robot.event_signature)."""
    periodic = tick % ticks_per_publish == 0
    for connection in connections:
        # Update before applying orders, so a fresh ACCEPTED is published
        # and held for one tick before the robot starts MOVING.
        before = connection.robot.event_signature()
        connection.robot.update(TICK_S)
        connection.apply_pending_messages()
        robot = connection.robot
        # The requests instant actions made (stateRequest, factsheetRequest) are answered here, in one place.
        if robot.factsheet_requested:
            robot.factsheet_requested = False
            connection.publish_factsheet()
        if periodic or robot.state_requested or robot.event_signature() != before:
            robot.state_requested = False
            connection.publish_state()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    robots = [
        Robot(f"robot_{i + 1:02d}", *parking_spot(i), vda_major=f"v{args.vda_version}") for i in range(args.robots)
    ]
    password = _robot_password()
    connections = [RobotConnection(robot, args.host, args.port, password) for robot in robots]

    running = True

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for connection in connections:
        connection.start()
    logging.info(
        "Simulating %d robots (VDA 5050 %s) against %s:%s",
        len(robots),
        VDA_VERSIONS[f"v{args.vda_version}"],
        args.host,
        args.port,
    )

    ticks_per_publish = max(1, round(args.interval / TICK_S))
    tick = 0
    next_tick = time.monotonic()
    while running:
        step(connections, tick, ticks_per_publish)
        tick += 1
        next_tick += TICK_S
        time.sleep(max(0.0, next_tick - time.monotonic()))

    logging.info("Shutting down")
    for connection in connections:
        connection.stop()


if __name__ == "__main__":
    main()
