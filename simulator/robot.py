from datetime import datetime, timezone

MANUFACTURER = "ActuNode"
VDA5050_VERSION = "2.1.0"
MAP_ID = "warehouse"

# Battery drained per move() call. Real drain per meter comes with motion (Day 3).
BATTERY_PER_MOVE = 1.0


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Robot:
    def __init__(self, robot_id: str, x: float = 0.0, y: float = 0.0):
        self.robot_id = robot_id

        self.x = x
        self.y = y
        self.theta = 0.0

        self.battery = 100.0
        self.charging = False

        # Mission state machine (Day 3): IDLE -> ACCEPTED -> MOVING -> COMPLETED
        self.mission_status = "IDLE"
        self.order_id = ""

        self.errors: list[dict] = []
        self._header_id = 0

    def move(self, target_x: float, target_y: float) -> None:
        self.mission_status = "MOVING"

        self.x = target_x
        self.y = target_y

        self.battery = max(0.0, self.battery - BATTERY_PER_MOVE)

    def stop(self) -> None:
        self.mission_status = "IDLE"

    def status(self) -> None:
        print(
            f"{self.robot_id} | "
            f"{self.mission_status} | "
            f"x={self.x} y={self.y} | "
            f"battery={self.battery:g}%"
        )

    def next_header_id(self) -> int:
        self._header_id += 1
        return self._header_id

    def header(self) -> dict:
        """Fields every VDA 5050 message starts with."""
        return {
            "headerId": self.next_header_id(),
            "timestamp": utc_timestamp(),
            "version": VDA5050_VERSION,
            "manufacturer": MANUFACTURER,
            "serialNumber": self.robot_id,
        }

    def state_message(self) -> dict:
        """VDA 5050 `state` message. ActuNode-specific fields go under `actunode`."""
        return {
            **self.header(),
            "orderId": self.order_id,
            "orderUpdateId": 0,
            "lastNodeId": "",
            "lastNodeSequenceId": 0,
            "nodeStates": [],
            "edgeStates": [],
            "driving": self.mission_status == "MOVING",
            "operatingMode": "AUTOMATIC",
            "agvPosition": {
                "x": self.x,
                "y": self.y,
                "theta": self.theta,
                "mapId": MAP_ID,
                "positionInitialized": True,
            },
            "batteryState": {
                "batteryCharge": round(self.battery, 1),
                "charging": self.charging,
            },
            "actionStates": [],
            "errors": self.errors,
            "safetyState": {"eStop": "NONE", "fieldViolation": False},
            "actunode": {"missionStatus": self.mission_status},
        }

    def connection_message(self, connection_state: str) -> dict:
        """VDA 5050 `connection` message: ONLINE, OFFLINE or CONNECTIONBROKEN."""
        return {**self.header(), "connectionState": connection_state}
