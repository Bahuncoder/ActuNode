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

# Robots park in a grid in the charging area (x 0-12 m, y 0-4 m) until missions arrive.
# Ten robots fill it; more spill over into rows above.
PARKING_COLUMNS = 5
PARKING_ORIGIN = (1.2, 1.2)
PARKING_SPACING = (2.2, 2.0)
MAX_ROBOTS = 50

# Physics step. State is published every --interval and on every state event.
TICK_S = 0.1


def parking_spot(index: int) -> tuple[float, float]:
    column, row = index % PARKING_COLUMNS, index // PARKING_COLUMNS
    return (
        round(PARKING_ORIGIN[0] + column * PARKING_SPACING[0], 2),
        round(PARKING_ORIGIN[1] + row * PARKING_SPACING[1], 2),
    )


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
        if periodic or connection.robot.event_signature() != before:
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
