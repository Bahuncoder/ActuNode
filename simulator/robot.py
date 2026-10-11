import json
import math
from datetime import UTC, datetime

MANUFACTURER = "ActuNode"
# Topic major version -> protocol version a robot reports (D-15). 2.1 is the default.
VDA_VERSIONS = {"v2": "2.1.0", "v3": "3.0.0"}
VDA5050_VERSION = VDA_VERSIONS["v2"]
MAP_ID = "warehouse"

SPEED_M_PER_S = 1.0
BATTERY_PER_METER = 0.2
# (x_min, y_min, x_max, y_max) of the warehouse map's charging zone, same as
# frontend/src/WarehouseMap.tsx and backend/app/warehouse.py.
CHARGING_AREA = (0.0, 0.0, 12.0, 4.0)
# % per second; fast so a demo robot is full again within two minutes.
CHARGE_PER_S = 1.0

# Mission state machine: IDLE -> ACCEPTED -> MOVING -> COMPLETED
# Failure injection can put a robot on a route into BLOCKED until cleared;
# an empty battery ends the mission in FAILED.
IDLE = "IDLE"
ACCEPTED = "ACCEPTED"
MOVING = "MOVING"
COMPLETED = "COMPLETED"
BLOCKED = "BLOCKED"
# The robot cannot continue on its own (battery empty). Cleared by the next accepted order.
FAILED = "FAILED"

BLOCKED_PATH = "BLOCKED_PATH"


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _check_actions(actions, path: str) -> tuple[str, str] | None:
    if not isinstance(actions, list):
        return f"{path} must be a list", path
    for i, action in enumerate(actions):
        where = f"{path}[{i}]"
        if not isinstance(action, dict):
            return f"{where} must be an object", where
        for key in ("actionType", "actionId"):
            if not isinstance(action.get(key), str):
                return f"{where}.{key} must be a string", f"{where}.{key}"
    return None


def _check_node(node, path: str) -> tuple[str, str] | None:
    if not isinstance(node, dict):
        return f"{path} must be an object", path
    if not isinstance(node.get("nodeId"), str):
        return f"{path}.nodeId must be a string", f"{path}.nodeId"
    if not _is_int(node.get("sequenceId")):
        return f"{path}.sequenceId must be an integer", f"{path}.sequenceId"
    if "released" in node and not isinstance(node["released"], bool):
        return f"{path}.released must be a boolean", f"{path}.released"
    position = node.get("nodePosition")
    if not isinstance(position, dict):
        return f"node {node['nodeId']} has no nodePosition", f"{path}.nodePosition"
    for axis in ("x", "y"):
        if not _is_number(position.get(axis)):
            return f"{path}.nodePosition.{axis} must be a finite number", f"{path}.nodePosition.{axis}"
    if "mapId" in position and not isinstance(position["mapId"], str):
        return f"{path}.nodePosition.mapId must be a string", f"{path}.nodePosition.mapId"
    return _check_actions(node.get("actions", []), f"{path}.actions")


def _check_edge(edge, path: str) -> tuple[str, str] | None:
    if not isinstance(edge, dict):
        return f"{path} must be an object", path
    if not isinstance(edge.get("edgeId"), str):
        return f"{path}.edgeId must be a string", f"{path}.edgeId"
    if not _is_int(edge.get("sequenceId")):
        return f"{path}.sequenceId must be an integer", f"{path}.sequenceId"
    if "released" in edge and not isinstance(edge["released"], bool):
        return f"{path}.released must be a boolean", f"{path}.released"
    for key in ("startNodeId", "endNodeId"):
        if key in edge and not isinstance(edge[key], str):
            return f"{path}.{key} must be a string", f"{path}.{key}"
    return _check_actions(edge.get("actions", []), f"{path}.actions")


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Robot:
    def __init__(self, robot_id: str, x: float = 0.0, y: float = 0.0, vda_major: str = "v2"):
        if vda_major not in VDA_VERSIONS:
            raise ValueError(f"unsupported VDA 5050 major version {vda_major!r}; use one of {list(VDA_VERSIONS)}")
        self.robot_id = robot_id
        self.vda_major = vda_major

        self.x = x
        self.y = y
        self.theta = 0.0

        self.battery = 100.0
        self.charging = False

        self.mission_status = IDLE
        self.order_id = ""
        self.order_update_id = 0
        self.last_node_id = ""
        self.last_node_sequence_id = 0

        # VDA 5050 keeps the *remaining* nodes/edges of the order in the state.
        self.node_states: list[dict] = []
        self.edge_states: list[dict] = []
        self.action_states: list[dict] = []
        self._node_positions: dict[str, tuple[float, float]] = {}
        self._actions_by_node: dict[str, list[str]] = {}

        self.errors: list[dict] = []
        # Speed over the last update (m/s); 0 at standstill, so `driving` is only true when the robot moved.
        self._velocity = 0.0
        self._moved = 0.0
        # VDA 5050: headerId counts up per topic, starting at 1.
        self._header_ids: dict[str, int] = {}

    @property
    def busy(self) -> bool:
        return self.mission_status in (ACCEPTED, MOVING, BLOCKED)

    # --- Orders -----------------------------------------------------------

    def handle_order_payload(self, payload: bytes) -> bool:
        """Accept or reject a raw order message. Rejections are reported in `errors`."""
        try:
            order = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._reject("", f"order is not valid JSON: {exc}")
            return False
        if not isinstance(order, dict):
            self._reject("", "order must be a JSON object")
            return False
        return self.accept_order(order)

    def accept_order(self, order: dict) -> bool:
        """Validate, then replace the mission. Nothing is mutated before validation passes."""
        order_id = str(order.get("orderId", ""))
        if order_id and order_id == self.order_id and isinstance(order.get("orderUpdateId", 0), int):
            update_id = order.get("orderUpdateId", 0)
            if update_id == self.order_update_id:
                # VDA 5050 2.1: same orderId and orderUpdateId as the current order is a duplicate; ignore it.
                return True
            if update_id < self.order_update_id:
                self._reject(
                    order_id,
                    f"orderUpdateId {update_id} is older than {self.order_update_id}",
                    error_type="orderUpdateError",
                )
                return False
            # A higher orderUpdateId falls through and is handled like a new order for now;
            # real order updates (keeping progress, stitching at the base node) are a later feature.
        problem = self._check_order(order)
        if problem:
            self._reject(order_id, *problem)
            return False

        nodes = sorted(order["nodes"], key=lambda node: node["sequenceId"])
        edges = sorted(order.get("edges", []), key=lambda edge: edge["sequenceId"])

        self.order_id = order_id
        self.order_update_id = order.get("orderUpdateId", 0)
        self.node_states = [
            {
                "nodeId": node["nodeId"],
                "sequenceId": node["sequenceId"],
                "released": True,
                "nodePosition": {"x": node["nodePosition"]["x"], "y": node["nodePosition"]["y"], "mapId": MAP_ID},
            }
            for node in nodes
        ]
        self.edge_states = [
            {"edgeId": edge["edgeId"], "sequenceId": edge["sequenceId"], "released": True} for edge in edges
        ]
        self._node_positions = {
            node["nodeId"]: (node["nodePosition"]["x"], node["nodePosition"]["y"]) for node in nodes
        }
        self._actions_by_node = {
            node["nodeId"]: [action["actionId"] for action in node.get("actions", [])] for node in nodes
        }
        self.action_states = [
            {"actionId": action["actionId"], "actionType": action["actionType"], "actionStatus": "WAITING"}
            for node in nodes
            for action in node.get("actions", [])
        ]
        self.errors = []
        self.mission_status = ACCEPTED
        return True

    def _check_order(self, order: dict) -> tuple[str, str | None] | None:
        """Return (description, offending field or None) for the first problem, else None."""
        if self.battery <= 0:
            return "battery is empty; robot cannot drive", None
        if self.busy:
            return f"robot is busy with order {self.order_id}", None
        if order.get("serialNumber") != self.robot_id:
            return f"order is addressed to {order.get('serialNumber')!r}, not {self.robot_id!r}", None
        if not order.get("orderId"):
            return "order has no orderId", "orderId"
        if not isinstance(order["orderId"], str):
            return "orderId must be a string", "orderId"
        if "orderUpdateId" in order and not _is_int(order["orderUpdateId"]):
            return "orderUpdateId must be an integer", "orderUpdateId"
        nodes = order.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return "order has no nodes", "nodes"
        for i, node in enumerate(nodes):
            problem = _check_node(node, f"nodes[{i}]")
            if problem:
                return problem
        edges = order.get("edges", [])
        if not isinstance(edges, list):
            return "edges must be a list", "edges"
        for i, edge in enumerate(edges):
            problem = _check_edge(edge, f"edges[{i}]")
            if problem:
                return problem
        return None

    def _reject(
        self, order_id: str, description: str, field: str | None = None, error_type: str = "orderError"
    ) -> None:
        # Replace an earlier rejection, but keep other errors (e.g. pathBlocked).
        self._drop_errors("orderError")
        self._drop_errors("orderUpdateError")
        references = [{"referenceKey": "orderId", "referenceValue": order_id}] if order_id else []
        if field:
            references.append({"referenceKey": "field", "referenceValue": field})
        self.errors.append(
            {
                "errorType": error_type,
                "errorLevel": "WARNING",
                "errorDescription": description,
                "errorReferences": references,
            }
        )

    def stop(self) -> None:
        """Abandon the current mission and stand still."""
        self.mission_status = IDLE
        self._velocity = 0.0
        self.node_states = []
        self.edge_states = []
        self._drop_errors("pathBlocked")

    # --- Failure injection ------------------------------------------------

    def handle_command_payload(self, payload: bytes) -> str:
        """Apply an ActuNode failure-injection command. Returns what happened, for the log."""
        try:
            command = json.loads(payload)
            failure = command["failure"]
            action = command.get("action", "inject")
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, KeyError):
            return "ignored malformed command"

        if failure != BLOCKED_PATH:
            return f"ignored unknown failure {failure!r}"
        if action == "inject":
            return "path blocked" if self.block_path() else f"ignored BLOCKED_PATH while {self.mission_status}"
        if action == "clear":
            return "path cleared" if self.clear_blocked_path() else "ignored clear: not blocked"
        return f"ignored unknown action {action!r}"

    def block_path(self) -> bool:
        """Something blocks the route: stop in place and report pathBlocked."""
        if self.mission_status not in (ACCEPTED, MOVING):
            return False

        on_edge = (
            self.edge_states
            and self.node_states
            and self.edge_states[0]["sequenceId"] < self.node_states[0]["sequenceId"]
        )
        if on_edge:
            reference = {"referenceKey": "edgeId", "referenceValue": self.edge_states[0]["edgeId"]}
            description = f"Path blocked on edge {self.edge_states[0]['edgeId']}"
        else:
            reference = {"referenceKey": "nodeId", "referenceValue": self.node_states[0]["nodeId"]}
            description = f"Path blocked on the way to {self.node_states[0]['nodeId']}"

        self._drop_errors("pathBlocked")
        self.errors.append(
            {
                "errorType": "pathBlocked",
                "errorLevel": "WARNING",
                "errorDescription": description,
                "errorReferences": [reference, {"referenceKey": "orderId", "referenceValue": self.order_id}],
            }
        )
        self.mission_status = BLOCKED
        self._velocity = 0.0
        return True

    def clear_blocked_path(self) -> bool:
        if self.mission_status != BLOCKED:
            return False
        self._drop_errors("pathBlocked")
        self.mission_status = MOVING
        return True

    def _drop_errors(self, error_type: str) -> None:
        self.errors = [error for error in self.errors if error["errorType"] != error_type]

    # --- Simulation -------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance the simulation by `dt` seconds."""
        self._moved = 0.0
        self._velocity = 0.0
        if self.mission_status == ACCEPTED:
            self.mission_status = MOVING
            return
        if self.mission_status != MOVING:
            self._charge(dt)
            return

        self.charging = False
        # Never drive further than the remaining battery allows.
        budget = min(SPEED_M_PER_S * dt, self.battery / BATTERY_PER_METER)
        while self.node_states and budget > 0:
            node_id = self.node_states[0]["nodeId"]
            target_x, target_y = self._node_positions[node_id]
            dx, dy = target_x - self.x, target_y - self.y
            distance = math.hypot(dx, dy)

            if distance > budget:
                self.theta = math.atan2(dy, dx)
                self.x += dx / distance * budget
                self.y += dy / distance * budget
                self._drain(budget)
                break

            if distance > 0:
                self.theta = math.atan2(dy, dx)
            self.x, self.y = target_x, target_y
            self._drain(distance)
            budget -= distance
            self._arrive(node_id)

        self._velocity = self._moved / dt
        if not self.node_states:
            self.mission_status = COMPLETED
            # Rejections of orders sent while busy no longer apply.
            self._drop_errors("orderError")
        elif self.battery <= 0:
            self._fail_battery_empty()
        if self.mission_status != MOVING:
            self._velocity = 0.0  # arrived or stopped: standing still

    def _charge(self, dt: float) -> None:
        x_min, y_min, x_max, y_max = CHARGING_AREA
        in_area = x_min <= self.x <= x_max and y_min <= self.y <= y_max
        self.charging = not self.busy and self.battery < 100 and in_area
        if not self.charging:
            return
        self.battery = min(100.0, self.battery + CHARGE_PER_S * dt)
        self.charging = self.battery < 100  # full: stop reporting charging
        if self.battery > 0:
            # The FATAL error means "needs a human"; once charged the robot can work again, and
            # keeping it would make a fleet manager stop sending orders.
            self._drop_errors("batteryEmpty")

    def _fail_battery_empty(self) -> None:
        next_node = self.node_states[0]["nodeId"]
        self.mission_status = FAILED
        self._drop_errors("batteryEmpty")
        self.errors.append(
            {
                "errorType": "batteryEmpty",
                "errorLevel": "FATAL",
                "errorDescription": f"Battery empty; stopped at ({self.x:.1f}, {self.y:.1f}) on the way to {next_node}",
                "errorReferences": [
                    {"referenceKey": "nodeId", "referenceValue": next_node},
                    {"referenceKey": "orderId", "referenceValue": self.order_id},
                ],
            }
        )

    def _arrive(self, node_id: str) -> None:
        node = self.node_states.pop(0)
        self.last_node_id = node_id
        self.last_node_sequence_id = node["sequenceId"]
        if self.edge_states and self.edge_states[0]["sequenceId"] < node["sequenceId"]:
            self.edge_states.pop(0)

        # Pick/drop happen instantly in the simulator.
        finished = set(self._actions_by_node.get(node_id, []))
        for action in self.action_states:
            if action["actionId"] in finished:
                action["actionStatus"] = "FINISHED"

    def _drain(self, meters: float) -> None:
        self._moved += meters
        remaining = self.battery - meters * BATTERY_PER_METER
        # Snap float residue (e.g. 1e-17) to exactly empty.
        self.battery = remaining if remaining > 1e-9 else 0.0

    def status(self) -> None:
        print(f"{self.robot_id} | {self.mission_status} | x={self.x:.1f} y={self.y:.1f} | battery={self.battery:.1f}%")

    # --- Messages ---------------------------------------------------------

    def next_header_id(self, topic_name: str) -> int:
        self._header_ids[topic_name] = self._header_ids.get(topic_name, 0) + 1
        return self._header_ids[topic_name]

    def header(self, topic_name: str) -> dict:
        """Fields every VDA 5050 message starts with."""
        return {
            "headerId": self.next_header_id(topic_name),
            "timestamp": utc_timestamp(),
            "version": VDA_VERSIONS[self.vda_major],
            "manufacturer": MANUFACTURER,
            "serialNumber": self.robot_id,
        }

    def event_signature(self) -> tuple:
        """What VDA 5050 says must trigger a state message when it changes (2.1 section 6.10, 3.0 section 6.6)."""
        return (
            self.mission_status,
            self.last_node_id,
            self.last_node_sequence_id,
            len(self.node_states),
            len(self.edge_states),
            tuple((action["actionId"], action["actionStatus"]) for action in self.action_states),
            tuple(error["errorType"] for error in self.errors),
            self._velocity > 0,
            self.order_id,
            self.order_update_id,
        )

    def state_message(self) -> dict:
        """VDA 5050 `state` message in the robot's version. ActuNode-specific fields go under `actunode`."""
        # Rounding can push pi up to 3.142; the spec range is [-pi, pi].
        theta = max(-math.pi, min(math.pi, round(self.theta, 3)))
        position = {"x": round(self.x, 3), "y": round(self.y, 3), "theta": theta, "mapId": MAP_ID}
        state = {
            **self.header("state"),
            "orderId": self.order_id,
            "orderUpdateId": self.order_update_id,
            "lastNodeId": self.last_node_id,
            "lastNodeSequenceId": self.last_node_sequence_id,
            "nodeStates": [{**node, "nodePosition": dict(node["nodePosition"])} for node in self.node_states],
            "edgeStates": [dict(edge) for edge in self.edge_states],
            "driving": self._velocity > 0,
            "operatingMode": "AUTOMATIC",
            "velocity": {"vx": round(self._velocity, 3), "vy": 0.0, "omega": 0.0},
            "actionStates": [dict(action) for action in self.action_states],
            "errors": [dict(error) for error in self.errors],
            "actunode": {"missionStatus": self.mission_status},
        }
        if self.vda_major == "v3":
            # 3.0 renamed these (see docs/research/VDA5050_3_0.md) and requires instantActionStates.
            state["mobileRobotPosition"] = {**position, "localized": True}
            state["powerSupply"] = {"stateOfCharge": round(self.battery, 1), "charging": self.charging}
            state["safetyState"] = {"activeEmergencyStop": "NONE", "fieldViolation": False}
            state["instantActionStates"] = []
        else:
            state["agvPosition"] = {**position, "positionInitialized": True}
            state["batteryState"] = {"batteryCharge": round(self.battery, 1), "charging": self.charging}
            state["safetyState"] = {"eStop": "NONE", "fieldViolation": False}
        return state

    def factsheet_message(self) -> dict:
        """VDA 5050 `factsheet` in the robot's version. Only what the simulator really does; the schemas
        require every section below, so numbers it has no model for are nominal and noted."""
        v3 = self.vda_major == "v3"
        # Nominal body size and no acceleration model: speed changes instantly, so acceleration is a stand-in.
        body = {"width": 0.6, "length": 0.8}
        # pick and drop at nodes; the backend tags the load with an optional loadId.
        pick_drop = [
            {
                "actionType": action_type,
                "actionScopes": ["NODE"],
                "actionParameters": [{"key": "loadId", "valueDataType": "STRING", "isOptional": True}],
                # The 3.0.0 text says boolean, but the official schema types these two as string.
                **({"pauseAllowed": "false", "cancelAllowed": "false"} if v3 else {}),
            }
            for action_type in ("pick", "drop")
        ]
        # The simulator handles no instantActions yet, so none are listed.
        features = {"optionalParameters": [], "mobileRobotActions" if v3 else "agvActions": pick_drop}
        if v3:
            return {
                **self.header("factsheet"),
                "typeSpecification": {
                    "seriesName": "ActuNode simulated AMR",
                    # The schema requires mobileRobotKinematic but only defines mobileRobotKinematics: send both.
                    "mobileRobotKinematic": "DIFFERENTIAL",
                    "mobileRobotKinematics": "DIFFERENTIAL",
                    "mobileRobotClass": "CARRIER",
                    "maximumLoadMass": 100,  # nominal: the simulator has no mass model, but it does carry loads
                    "localizationTypes": ["NATURAL"],
                    "navigationTypes": ["VIRTUAL_LINE_GUIDED"],
                },
                "physicalParameters": {
                    "minimumSpeed": 0.0,
                    "maximumSpeed": SPEED_M_PER_S,
                    "maximumAcceleration": 10.0,
                    "maximumDeceleration": 10.0,
                    "minimumHeight": 0.3,
                    "maximumHeight": 0.3,
                    **body,
                },
                "protocolLimits": {
                    "maximumStringLengths": {},
                    "maximumArrayLengths": {},
                    "timing": {"minimumOrderInterval": 0.1, "minimumStateInterval": 0.1},
                },
                "protocolFeatures": features,
                "mobileRobotGeometry": {},
                "loadSpecification": {},
            }
        return {
            **self.header("factsheet"),
            "typeSpecification": {
                "seriesName": "ActuNode simulated AMR",
                # A point robot that turns to face its heading: the closest allowed kinematics is DIFF.
                "agvKinematic": "DIFF",
                "agvClass": "CARRIER",
                "maxLoadMass": 100,  # nominal: the simulator has no mass model, but it does carry loads
                "localizationTypes": ["NATURAL"],
                "navigationTypes": ["VIRTUAL_LINE_GUIDED"],
            },
            "physicalParameters": {
                "speedMin": 0.0,
                "speedMax": SPEED_M_PER_S,
                "accelerationMax": 10.0,
                "decelerationMax": 10.0,
                "heightMin": 0.3,
                "heightMax": 0.3,
                **body,
            },
            "protocolLimits": {
                "maxStringLens": {},
                "maxArrayLens": {},
                "timing": {"minOrderInterval": 0.1, "minStateInterval": 0.1},
            },
            "protocolFeatures": features,
            "agvGeometry": {},
            "loadSpecification": {},
        }

    def connection_message(self, connection_state: str) -> dict:
        """VDA 5050 `connection` message: ONLINE, OFFLINE or CONNECTIONBROKEN (CONNECTION_BROKEN in 3.0)."""
        if self.vda_major == "v3" and connection_state == "CONNECTIONBROKEN":
            connection_state = "CONNECTION_BROKEN"
        return {**self.header("connection"), "connectionState": connection_state}
