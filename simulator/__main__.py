"""Run simulated AMRs that publish VDA 5050 state over MQTT.

    python -m simulator --robots 3
"""

import argparse
import logging
import os
import signal
import time

from simulator.publisher import RobotConnection
from simulator.robot import Robot

# Robots park side by side in the charging area until missions arrive.
PARKING_X = 1.5
PARKING_Y = 2.0
PARKING_SPACING = 2.5

# Physics step. State is published every --interval and on every mission status change.
TICK_S = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="simulator", description="ActuNode AMR simulator")
    parser.add_argument("--robots", type=int, default=int(os.getenv("ACTUNODE_SIM_ROBOTS", "3")))
    parser.add_argument("--host", default=os.getenv("ACTUNODE_MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ACTUNODE_MQTT_PORT", "1883")))
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between state messages")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    robots = [
        Robot(f"robot_{i + 1:02d}", x=PARKING_X + i * PARKING_SPACING, y=PARKING_Y)
        for i in range(args.robots)
    ]
    connections = [RobotConnection(robot, args.host, args.port) for robot in robots]

    running = True

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for connection in connections:
        connection.start()
    logging.info("Simulating %d robots against %s:%s", len(robots), args.host, args.port)

    ticks_per_publish = max(1, round(args.interval / TICK_S))
    tick = 0
    next_tick = time.monotonic()
    while running:
        periodic = tick % ticks_per_publish == 0
        for connection in connections:
            # Update before applying orders, so a fresh ACCEPTED is published
            # and held for one tick before the robot starts MOVING.
            before = connection.robot.mission_status
            connection.robot.update(TICK_S)
            changed = connection.robot.mission_status != before
            if connection.apply_pending_messages():
                changed = True
            if periodic or changed:
                connection.publish_state()
        tick += 1
        next_tick += TICK_S
        time.sleep(max(0.0, next_tick - time.monotonic()))

    logging.info("Shutting down")
    for connection in connections:
        connection.stop()


if __name__ == "__main__":
    main()
