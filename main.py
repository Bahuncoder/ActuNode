"""Offline playground: run one mission through the robot state machine, no MQTT needed.

python3 main.py
"""

from simulator.robot import COMPLETED, Robot

robot = Robot("robot_01", x=3.5, y=2.0)
robot.status()

# Pallet P-1042: Receiving Door 2 -> Storage A17 (same shape the backend sends).
order = {
    "serialNumber": "robot_01",
    "orderId": "order-demo",
    "nodes": [
        {
            "nodeId": "RECEIVING_DOOR_2",
            "sequenceId": 0,
            "nodePosition": {"x": 2.0, "y": 14.0},
            "actions": [{"actionId": "pick-1", "actionType": "pick"}],
        },
        {
            "nodeId": "STORAGE_A17",
            "sequenceId": 2,
            "nodePosition": {"x": 14.0, "y": 18.0},
            "actions": [{"actionId": "drop-1", "actionType": "drop"}],
        },
    ],
    "edges": [{"edgeId": "RECEIVING_DOOR_2->STORAGE_A17", "sequenceId": 1}],
}

robot.accept_order(order)
robot.status()

seconds = 0
while robot.mission_status != COMPLETED:
    for _ in range(10):
        robot.update(0.1)
    seconds += 1
    if seconds % 4 == 0 or robot.mission_status == COMPLETED:
        print(f"t={seconds:>2}s  last node={robot.last_node_id or '-':<17}", end="")
        robot.status()
