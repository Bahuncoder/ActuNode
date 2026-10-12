"""Offline playground: run one mission through the robot state machine, no MQTT needed.

python3 main.py
"""

from simulator.robot import COMPLETED, Robot

robot = Robot("robot_01", x=3.5, y=2.0)
robot.status()

# Pallet P-1042: Receiving Door 2 -> Storage A17, the same shape the backend sends: the first node is where
# the robot stands (VDA 5050: the first node must be trivially reachable, D-35).
order = {
    "serialNumber": "robot_01",
    "orderId": "order-demo",
    "orderUpdateId": 0,
    "nodes": [
        {"nodeId": "start", "sequenceId": 0, "released": True, "nodePosition": {"x": 3.5, "y": 2.0}, "actions": []},
        {
            "nodeId": "RECEIVING_DOOR_2",
            "sequenceId": 2,
            "released": True,
            "nodePosition": {"x": 2.0, "y": 14.0},
            "actions": [{"actionId": "pick-1", "actionType": "pick", "blockingType": "HARD"}],
        },
        {
            "nodeId": "STORAGE_A17",
            "sequenceId": 4,
            "released": True,
            "nodePosition": {"x": 14.0, "y": 18.0},
            "actions": [{"actionId": "drop-1", "actionType": "drop", "blockingType": "HARD"}],
        },
    ],
    "edges": [
        {"edgeId": "start->RECEIVING_DOOR_2", "sequenceId": 1, "released": True, "actions": []},
        {"edgeId": "RECEIVING_DOOR_2->STORAGE_A17", "sequenceId": 3, "released": True, "actions": []},
    ],
}

if not robot.accept_order(order):
    raise SystemExit(f"order rejected: {robot.errors}")
robot.status()

seconds = 0
while robot.mission_status != COMPLETED:
    if seconds > 120:
        raise SystemExit(f"mission did not complete: {robot.mission_status}")
    for _ in range(10):
        robot.update(0.1)
    seconds += 1
    if seconds % 4 == 0 or robot.mission_status == COMPLETED:
        print(f"t={seconds:>2}s  last node={robot.last_node_id or '-':<17}", end="")
        robot.status()
