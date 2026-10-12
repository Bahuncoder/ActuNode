import copy
import json
import logging
import math
from datetime import UTC, datetime

log = logging.getLogger(__name__)

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
# An order with a horizon stops at its last released node: MOVING -> WAITING until an order update
# releases more (-> MOVING again) or ends the order (-> COMPLETED).
# Failure injection can put a robot on a route into BLOCKED until cleared;
# an empty battery ends the mission in FAILED.
IDLE = "IDLE"
ACCEPTED = "ACCEPTED"
MOVING = "MOVING"
COMPLETED = "COMPLETED"
BLOCKED = "BLOCKED"
WAITING = "WAITING"
# The robot cannot continue on its own (battery empty). Cleared by the next accepted order.
FAILED = "FAILED"
# The order was cancelled by a cancelOrder instant action; the robot is idle again.
CANCELLED = "CANCELLED"

BLOCKED_PATH = "BLOCKED_PATH"

# A first node within this distance of the robot is reachable when the order names no allowedDeviationXY.
DEFAULT_TOLERANCE_M = 0.25
# newBaseRequest is true when the decision point is this close (m).
NEW_BASE_DISTANCE_M = 1.0
# The only action types the simulator performs.
SUPPORTED_ACTIONS = ("pick", "drop")
# Why an order was rejected -> (2.1 errorType, 3.0 errorType), all WARNING (D-35). Where a version names
# no error, the closest 2.1 name is reused; the stitch case names none in either version.
ORDER_ERRORS = {
    "malformed": ("validationError", "VALIDATION_FAILURE"),
    "action": ("orderError", "INVALID_ORDER_ACTION"),
    "active": ("orderError", "OTHER_ORDER_ACTIVE"),
    "range": ("orderError", "START_NODE_OUT_OF_RANGE"),
    "outdated": ("orderUpdateError", "OUTDATED_ORDER_UPDATE"),
    "same": ("orderUpdateError", "SAME_ORDER_UPDATE_ID"),
    "cancelled": ("orderUpdateError", "ORDER_UPDATE_FOLLOWING_CANCEL"),
    # An update while the battery is empty: 3.0 names no error for it; this is the closest ("until operating
    # mode allows for new orders"). 2.1 has orderUpdateError for any failed update.
    "unavailable": ("orderUpdateError", "MOBILE_ROBOT_NOT_AVAILABLE"),
    "stitch": ("orderUpdateError", "VALIDATION_FAILURE"),
    "other": ("orderError", "orderError"),  # e.g. empty battery: neither version names an error
}
# NO_ORDER_TO_CANCEL stays "until new order is accepted" (3.0 section 6.6.7), like a rejection.
REJECTION_TYPES = {name for pair in ORDER_ERRORS.values() for name in pair} | {"noOrderToCancel", "NO_ORDER_TO_CANCEL"}

# Instant actions the simulator performs (2.1 section 6.8.1, 3.0 section 6.2.1); clearInstantActions is 3.0 only.
INSTANT_ACTIONS = ("cancelOrder", "startPause", "stopPause", "stateRequest", "factsheetRequest")
INSTANT_ACTIONS_V3 = (*INSTANT_ACTIONS, "clearInstantActions")
# Instant action states kept. 3.0 allows an URGENT INSTANT_ACTION_STATES_FULL error when the list grows too
# long; the simulator drops the oldest finished/failed one instead, so it never gets there.
MAX_INSTANT_ACTION_STATES = 50
# One instantActions message is handled up to this many actions: more would make the state (every failed one
# gets a state) outgrow the broker's max_packet_size.
MAX_INSTANT_ACTIONS_PER_MESSAGE = 50
ID_IN_USE = "actionId already in use"


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_deviation(value, v3: bool) -> bool:
    """3.0: ellipse {a, b, theta}; 2.1: radius in meters."""
    if v3:
        return isinstance(value, dict) and all(_is_number(value.get(key)) for key in ("a", "b", "theta"))
    return _is_number(value) and value >= 0


def _check_parameters(parameters, path: str) -> tuple[str, str] | None:
    """actionParameters, when present: a list of objects with a string key (the value may be any JSON)."""
    if not isinstance(parameters, list):
        return f"{path} must be a list", path
    for i, parameter in enumerate(parameters):
        if not isinstance(parameter, dict) or not isinstance(parameter.get("key"), str):
            return f"{path}[{i}] must be an object with a string key", f"{path}[{i}]"
    return None


def _check_actions(actions, path: str, parameters: bool = True) -> tuple[str, str] | None:
    if not isinstance(actions, list):
        return f"{path} must be a list", path
    for i, action in enumerate(actions):
        where = f"{path}[{i}]"
        if not isinstance(action, dict):
            return f"{where} must be an object", where
        for key in ("actionType", "actionId"):
            if not isinstance(action.get(key), str):
                return f"{where}.{key} must be a string", f"{where}.{key}"
        if parameters and "actionParameters" in action:
            problem = _check_parameters(action["actionParameters"], f"{where}.actionParameters")
            if problem:
                return problem
    return None


def _check_node(node, path: str, v3: bool) -> tuple[str, str] | None:
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
    if "allowedDeviationXY" in position and not _is_deviation(position["allowedDeviationXY"], v3):
        what = "an object {a, b, theta}" if v3 else "a number"
        return f"{path}.nodePosition.allowedDeviationXY must be {what}", f"{path}.nodePosition.allowedDeviationXY"
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
        # 3.0 keeps instant actions apart; 2.1 puts them into action_states (ids in _instant_ids).
        self.instant_action_states: list[dict] = []
        self._instant_ids: set[str] = set()
        # startPause / stopPause (both versions report it as `paused`).
        self.paused = False
        # Set by factsheetRequest; the publisher publishes the factsheet and resets it.
        self.factsheet_requested = False
        # Set by stateRequest; the main loop publishes the state and resets it.
        self.state_requested = False
        # Loads the robot carries, as reported in `loads`.
        self.loads: list[dict] = []
        # Set by cancelOrder: further updates of that order are rejected.
        self.cancelled = False
        # Per sequenceId: the actions attached to a node/edge, and where the robot last stood.
        self._node_actions: dict[int, list[str]] = {}
        self._edge_actions: dict[int, list[str]] = {}
        self._load_ids: dict[str, str] = {}
        self._last_node_xy = (x, y)
        # The last order/update accepted, without headerId and timestamp, to recognise duplicates.
        self._last_order: dict = {}

        self.errors: list[dict] = []
        # Speed over the last update (m/s); 0 at standstill, so `driving` is only true when the robot moved.
        self._velocity = 0.0
        self._moved = 0.0
        # VDA 5050: headerId counts up per topic, starting at 1.
        self._header_ids: dict[str, int] = {}

    @property
    def busy(self) -> bool:
        """Working on an order: it neither charges nor takes a new one."""
        return self.mission_status in (ACCEPTED, MOVING, BLOCKED, WAITING)

    @property
    def idle(self) -> bool:
        """VDA 5050 (2.1 section 6.6, 3.0 section 6.1): nothing left to traverse and every action done."""
        return (
            not self.node_states
            and not self.edge_states
            and all(
                action["actionStatus"] in ("FINISHED", "FAILED")
                for action in self.action_states
                if action["actionId"] not in self._instant_ids  # 2.1 lists instant actions here too
            )
        )

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
        """Validate, then start a new order or apply an order update. Nothing is mutated before validation passes."""
        order_id = str(order.get("orderId", ""))
        problem = self._check_order(order)
        if problem:
            self._reject(order_id, *problem)
            return False
        problem = self._check_action_types(order)
        if problem:
            self._reject(order_id, *problem, kind="action")
            return False

        is_update = order_id == self.order_id
        # NOTE: a new order with orderUpdateId > 0 is accepted. 3.0 Figure 8 step 4 asks "Is orderUpdateId 0?",
        # but the outcome of that step is only in the figure, not in the text.
        if is_update:
            update_id = order.get("orderUpdateId", 0)
            if update_id < self.order_update_id:
                self._reject(
                    order_id, f"orderUpdateId {update_id} is older than {self.order_update_id}", kind="outdated"
                )
                return False
            if self.cancelled and (update_id > self.order_update_id or self.vda_major == "v3"):
                # 3.0 Figure 8 asks "follows cancel" (step 7) before "same orderUpdateId" (step 8). 2.1 still
                # ignores a repeat of the last update (a duplicate delivery) even after a cancel.
                self._reject(order_id, "order update for a cancelled order", kind="cancelled")
                return False
            if update_id == self.order_update_id:
                if self._comparable(order) == self._last_order or self.vda_major == "v2":
                    # Same orderId and orderUpdateId: a duplicate. 2.1 ignores any such message; 3.0 only
                    # an identical one and reports SAME_ORDER_UPDATE_ID for different content.
                    return True
                self._reject(order_id, f"orderUpdateId {update_id} was already used with other content", kind="same")
                return False
        if self.battery <= 0:
            # An update to a stopped order gets the "robot not available" error (see ORDER_ERRORS).
            self._reject(order_id, "battery is empty; robot cannot drive", kind="unavailable" if is_update else "other")
            return False
        # Atomic: if anything unexpected fails half way, the robot stays exactly as it was.
        before = copy.deepcopy(self.__dict__)
        try:
            return self._apply_update(order) if is_update else self._apply_new_order(order)
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(before)
            raise

    @staticmethod
    def _comparable(order: dict) -> dict:
        return {key: value for key, value in order.items() if key not in ("headerId", "timestamp")}

    def _apply_new_order(self, order: dict) -> bool:
        if not self.idle:
            self._reject(order["orderId"], f"robot is busy with order {self.order_id}", kind="active")
            return False
        nodes = sorted(order["nodes"], key=lambda node: node["sequenceId"])
        if not self._reachable(nodes[0]["nodePosition"]):
            self._reject(
                order["orderId"],
                f"first node {nodes[0]['nodeId']} is out of range of ({self.x:.1f}, {self.y:.1f})",
                "nodes[0].nodePosition",
                kind="range",
            )
            return False

        self.order_id = order["orderId"]
        self.order_update_id = order.get("orderUpdateId", 0)
        self.cancelled = False
        self.node_states = []
        self.edge_states = []
        # 2.1: action states are removed upon a new order, except running instant actions.
        self.action_states = [
            a for a in self.action_states if a["actionId"] in self._instant_ids and a["actionStatus"] == "RUNNING"
        ]
        self._instant_ids &= {a["actionId"] for a in self.action_states}
        self._node_actions = {}
        self._edge_actions = {}
        self._load_ids = {}
        self._add_to_order(nodes, sorted(order.get("edges", []), key=lambda edge: edge["sequenceId"]))
        self._last_order = self._comparable(order)
        self._clear_rejections()
        self.mission_status = ACCEPTED
        # The robot is at the first node: it counts as traversed, so it is not left in nodeStates.
        self._traverse(self.node_states.pop(0))
        return True

    def _apply_update(self, order: dict) -> bool:
        """Stitch an order update at the decision point (2.1 section 6.6, Figure 8)."""
        nodes = sorted(order["nodes"], key=lambda node: node["sequenceId"])
        node_id, sequence_id, _ = self._decision_point()
        if (nodes[0]["nodeId"], nodes[0]["sequenceId"]) != (node_id, sequence_id):
            self._reject(
                order["orderId"],
                f"update starts at {nodes[0]['nodeId']} (sequenceId {nodes[0]['sequenceId']}), "
                f"not at the decision point {node_id} (sequenceId {sequence_id})",
                "nodes[0]",
                kind="stitch",
            )
            return False

        # Everything after the decision point is horizon: the update's base and horizon replace it.
        for sequence, ids in list(self._node_actions.items()):
            if sequence > sequence_id:
                self._forget_actions(ids)
                del self._node_actions[sequence]
        for sequence, ids in list(self._edge_actions.items()):
            if sequence > sequence_id:
                self._forget_actions(ids)
                del self._edge_actions[sequence]
        self.node_states = [node for node in self.node_states if node["sequenceId"] <= sequence_id]
        self.edge_states = [edge for edge in self.edge_states if edge["sequenceId"] <= sequence_id]
        edges = sorted(order.get("edges", []), key=lambda edge: edge["sequenceId"])
        # The stitch node's actions are not run again.
        self._add_to_order(nodes[1:], [edge for edge in edges if edge["sequenceId"] > sequence_id])

        self.order_update_id = order.get("orderUpdateId", 0)
        self._last_order = self._comparable(order)
        self._clear_rejections()
        # FAILED: the battery was recharged (an update with an empty battery is rejected), so the fleet manager's
        # update resumes the order.
        if self.mission_status in (COMPLETED, WAITING, FAILED):
            if not self.node_states:
                self.mission_status = COMPLETED
            elif self._can_drive():
                self.mission_status = ACCEPTED if self.mission_status == COMPLETED else MOVING
            else:
                self.mission_status = WAITING
            self._enter_edge()
        return True

    def _add_to_order(self, nodes: list[dict], edges: list[dict]) -> None:
        """Add nodes, edges and their actions (in WAITING) to the remaining order."""
        for node in nodes:
            self.node_states.append(
                {
                    "nodeId": node["nodeId"],
                    "sequenceId": node["sequenceId"],
                    "released": node.get("released", True),
                    "nodePosition": {"x": node["nodePosition"]["x"], "y": node["nodePosition"]["y"], "mapId": MAP_ID},
                }
            )
            self._node_actions[node["sequenceId"]] = self._add_actions(node.get("actions", []))
        for edge in edges:
            self.edge_states.append(
                {"edgeId": edge["edgeId"], "sequenceId": edge["sequenceId"], "released": edge.get("released", True)}
            )
            self._edge_actions[edge["sequenceId"]] = self._add_actions(edge.get("actions", []))

    def _add_actions(self, actions: list[dict]) -> list[str]:
        for action in actions:
            self.action_states.append(
                {"actionId": action["actionId"], "actionType": action["actionType"], "actionStatus": "WAITING"}
            )
            load_id = next(
                (
                    p.get("value")
                    for p in action.get("actionParameters", [])
                    if isinstance(p, dict) and p.get("key") == "loadId"
                ),
                "",
            )
            self._load_ids[action["actionId"]] = load_id if isinstance(load_id, str) else ""
        return [action["actionId"] for action in actions]

    def _forget_actions(self, ids: list[str]) -> None:
        self.action_states = [action for action in self.action_states if action["actionId"] not in ids]
        for action_id in ids:
            self._load_ids.pop(action_id, None)

    def _reachable(self, position: dict) -> bool:
        """Within the first node's allowedDeviationXY (2.1 radius, 3.0 ellipse; 0 or absent: default tolerance)?"""
        dx, dy = self.x - position["x"], self.y - position["y"]
        deviation = position.get("allowedDeviationXY", 0)
        if isinstance(deviation, dict):
            a, b, theta = deviation["a"], deviation["b"], deviation["theta"]
            if a > 0 and b > 0:
                u = dx * math.cos(theta) + dy * math.sin(theta)
                v = -dx * math.sin(theta) + dy * math.cos(theta)
                return (u / a) ** 2 + (v / b) ** 2 <= 1
            deviation = 0
        return math.hypot(dx, dy) <= (deviation if deviation > 0 else DEFAULT_TOLERANCE_M)

    def _decision_point(self) -> tuple[str, int, tuple[float, float]]:
        """Last released node of the order: where the robot stops and where an update must start."""
        released = [node for node in self.node_states if node["released"]]
        if released:
            node = released[-1]
            return node["nodeId"], node["sequenceId"], (node["nodePosition"]["x"], node["nodePosition"]["y"])
        return self.last_node_id, self.last_node_sequence_id, self._last_node_xy

    def _can_drive(self) -> bool:
        """The next node and the edge leading to it are released."""
        if not self.node_states or not self.node_states[0]["released"]:
            return False
        edge = self.edge_states[0] if self.edge_states else None
        return not (edge and edge["sequenceId"] < self.node_states[0]["sequenceId"] and not edge["released"])

    @property
    def new_base_request(self) -> bool:
        """Horizon left and the decision point within NEW_BASE_DISTANCE_M (2.1 section 6.10.6)."""
        if not any(not node["released"] for node in self.node_states):
            return False
        x, y = self._decision_point()[2]
        return math.hypot(x - self.x, y - self.y) <= NEW_BASE_DISTANCE_M

    def _check_order(self, order: dict) -> tuple[str, str | None] | None:
        """Return (description, offending field or None) for the first malformed part, else None."""
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
            problem = _check_node(node, f"nodes[{i}]", self.vda_major == "v3")
            if problem:
                return problem
        edges = order.get("edges", [])
        if not isinstance(edges, list):
            return "edges must be a list", "edges"
        for i, edge in enumerate(edges):
            problem = _check_edge(edge, f"edges[{i}]")
            if problem:
                return problem
        return self._check_unique(nodes, edges)

    @staticmethod
    def _check_unique(nodes: list[dict], edges: list[dict]) -> tuple[str, str] | None:
        """sequenceId and actionId are unique within an order (nodes and edges share one sequence)."""
        sequences, action_ids = set(), set()
        for kind, items in (("nodes", nodes), ("edges", edges)):
            for i, item in enumerate(items):
                if item["sequenceId"] in sequences:
                    return f"sequenceId {item['sequenceId']} is used twice", f"{kind}[{i}].sequenceId"
                sequences.add(item["sequenceId"])
                for j, action in enumerate(item.get("actions", [])):
                    if action["actionId"] in action_ids:
                        return f"actionId {action['actionId']!r} is used twice", f"{kind}[{i}].actions[{j}].actionId"
                    action_ids.add(action["actionId"])
        return None

    @staticmethod
    def _check_action_types(order: dict) -> tuple[str, str] | None:
        """Only pick and drop are supported; the error names the field (3.0 section 6.1.4)."""
        for kind in ("nodes", "edges"):
            for i, item in enumerate(order.get(kind, [])):
                for j, action in enumerate(item.get("actions", [])):
                    if action["actionType"] not in SUPPORTED_ACTIONS:
                        return (
                            f"unsupported action type {action['actionType']!r}",
                            f"{kind}[{i}].actions[{j}].actionType",
                        )
        return None

    def _reject(self, order_id: str, description: str, field: str | None = None, kind: str = "malformed") -> None:
        # Replace an earlier rejection, but keep other errors (e.g. pathBlocked).
        self._clear_rejections()
        references = [{"referenceKey": "orderId", "referenceValue": order_id}] if order_id else []
        if field:
            references.append({"referenceKey": "field", "referenceValue": field})
        self.errors.append(
            {
                "errorType": ORDER_ERRORS[kind][self.vda_major == "v3"],
                "errorLevel": "WARNING",
                "errorDescription": description,
                "errorReferences": references,
            }
        )

    def _clear_rejections(self) -> None:
        """Rejections stay until a new order (or update) is accepted (2.1 section 6.6, 3.0 section 6.6.5.4)."""
        self.errors = [error for error in self.errors if error["errorType"] not in REJECTION_TYPES]

    # --- Instant actions ----------------------------------------------------

    def handle_instant_actions_payload(self, payload: bytes) -> bool:
        """Apply a raw instantActions message. False if it is malformed and was ignored: neither version names
        an error for a message that cannot be parsed, so the caller only logs it."""
        try:
            message = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        actions = message.get("actions") if isinstance(message, dict) else None
        # actionParameters are checked per action below: a bad one fails that action, not the message.
        if not isinstance(actions, list) or _check_actions(actions, "actions", parameters=False):
            return False
        if len(actions) > MAX_INSTANT_ACTIONS_PER_MESSAGE:
            log.warning(
                "%s: ignored %d instant actions beyond the first %d of the message",
                self.robot_id,
                len(actions) - MAX_INSTANT_ACTIONS_PER_MESSAGE,
                MAX_INSTANT_ACTIONS_PER_MESSAGE,
            )
            actions = actions[:MAX_INSTANT_ACTIONS_PER_MESSAGE]
        v3 = self.vda_major == "v3"
        # "Until new instant action is accepted" (3.0 section 6.6.7).
        self._drop_errors("INVALID_INSTANT_ACTION")
        invalid = []
        for action in actions:
            if action["actionType"] == "stateRequest":
                # The loop publishes when this is set; the event signature alone would miss a repeated request
                # with the same actionId (also one refused for reusing an id).
                self.state_requested = True
            in_use = self._id_in_use(action["actionId"])
            state = self._add_instant_state(action, in_use)
            if in_use:
                self._set_status(state, "FAILED", ID_IN_USE)
            elif action["actionType"] not in (INSTANT_ACTIONS_V3 if v3 else INSTANT_ACTIONS):
                self._set_status(state, "FAILED", f"unsupported instant action {action['actionType']!r}")
            elif "actionParameters" in action and _check_parameters(action["actionParameters"], "actionParameters"):
                # Same outcome as an unknown action (3.0 names no error for bad parameters): FAILED.
                self._set_status(state, "FAILED", "actionParameters must be a list of objects with a string key")
            else:
                getattr(self, f"_instant_{action['actionType']}")(action, state)
                continue
            invalid.append(action["actionId"])
            # 2.1 names no error for a failed instant action: only the FAILED action state reports it.
        if v3 and invalid:
            # One error per message, so a flood of bad actions cannot blow up the state message.
            self.errors.append(
                {
                    "errorType": "INVALID_INSTANT_ACTION",
                    "errorLevel": "WARNING",
                    "errorDescription": "invalid instant action",
                    "errorReferences": [{"referenceKey": "actionId", "referenceValue": i} for i in invalid],
                }
            )
        return True

    def _id_in_use(self, action_id: str) -> bool:
        return any(a["actionId"] == action_id for a in (*self.action_states, *self.instant_action_states))

    def _add_instant_state(self, action: dict, in_use: bool = False) -> dict:
        state = {"actionId": action["actionId"], "actionType": action["actionType"], "actionStatus": "WAITING"}
        v3 = self.vda_major == "v3"
        states = self.instant_action_states if v3 else self.action_states
        if not v3 and not in_use:  # a clashing id stays what it is: the state is marked by ID_IN_USE
            self._instant_ids.add(state["actionId"])
        instants = [a for a in states if v3 or self._is_instant(a)]
        if len(instants) >= MAX_INSTANT_ACTION_STATES:  # see MAX_INSTANT_ACTION_STATES
            old = next((a for a in instants if a["actionStatus"] in ("FINISHED", "FAILED")), None)
            if old:
                states[:] = [a for a in states if a is not old]
                if not any(a["actionId"] == old["actionId"] for a in states):
                    self._instant_ids.discard(old["actionId"])
        states.append(state)
        return state

    def _is_instant(self, state: dict) -> bool:
        """2.1 lists instant action states among the order's: by id, or a duplicate id that was refused."""
        return state["actionId"] in self._instant_ids or state.get("resultDescription") == ID_IN_USE

    def _instant_error(self, error_type: str, action: dict, description: str) -> None:
        self.errors.append(
            {
                "errorType": error_type,
                "errorLevel": "WARNING",
                "errorDescription": description,
                "errorReferences": [{"referenceKey": "actionId", "referenceValue": action["actionId"]}],
            }
        )

    def _instant_cancelOrder(self, action: dict, state: dict) -> None:
        parameters = action.get("actionParameters")
        wanted = next(
            (p.get("value") for p in parameters or [] if isinstance(p, dict) and p.get("key") == "orderId"), None
        )
        # 3.0 section 6.1.3.2: idle, or another orderId than the active one: FAILED. 2.1 has no such parameter.
        if self.idle or (self.vda_major == "v3" and wanted is not None and wanted != self.order_id):
            self._set_status(state, "FAILED", "no active order to cancel")
            error_type = "noOrderToCancel" if self.vda_major == "v2" else "NO_ORDER_TO_CANCEL"
            self._drop_errors(error_type)
            self._instant_error(error_type, action, "no active order to cancel")
            return
        # Everything is instant, so the robot stops at once. mission_status and errors other than a
        # blocked path stay as they are: errors persist until a new order is accepted.
        self.mission_status = CANCELLED
        self.cancelled = True
        self._velocity = 0.0
        self.node_states = []
        self.edge_states = []
        self._drop_errors("pathBlocked")
        for order_action in self.action_states:
            if order_action["actionId"] not in self._instant_ids and order_action["actionStatus"] in (
                "WAITING",
                "RUNNING",
            ):
                self._set_status(order_action, "FAILED", "order cancelled")
        self._set_status(state, "FINISHED")

    def _instant_startPause(self, action: dict, state: dict) -> None:
        # Idempotent: pausing a paused robot (and resuming a running one) is not an error in either version.
        self.paused = True
        self._set_status(state, "FINISHED")

    def _instant_stopPause(self, action: dict, state: dict) -> None:
        self.paused = False
        self._set_status(state, "FINISHED")

    def _instant_stateRequest(self, action: dict, state: dict) -> None:
        self._set_status(state, "FINISHED")

    def _instant_factsheetRequest(self, action: dict, state: dict) -> None:
        self.factsheet_requested = True
        self._set_status(state, "FINISHED")

    def _instant_clearInstantActions(self, action: dict, state: dict) -> None:
        # 3.0 removes finished/failed instant actions. This action's own state stays (FINISHED), so the
        # master can see that it worked; the next clear removes it.
        self.instant_action_states = [
            a for a in self.instant_action_states if a is state or a["actionStatus"] not in ("FINISHED", "FAILED")
        ]
        self._set_status(state, "FINISHED")

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
        if self.mission_status not in (ACCEPTED, MOVING) or not self.node_states:
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

    def _drop_errors(self, error_type: str) -> bool:
        """Remove errors of this type; True if there were any."""
        kept = [error for error in self.errors if error["errorType"] != error_type]
        removed = len(kept) != len(self.errors)
        self.errors = kept
        return removed

    # --- Simulation -------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance the simulation by `dt` seconds."""
        self._moved = 0.0
        self._velocity = 0.0
        if self.paused and self.busy:
            return  # startPause: no progress and no status change until stopPause
        if self.mission_status == ACCEPTED:
            self.mission_status = MOVING
            return
        if self.mission_status == WAITING:
            return  # at the decision point, until an order update releases more
        if self.mission_status != MOVING:
            self._charge(dt)
            return

        self.charging = False
        # Never drive further than the remaining battery allows.
        budget = min(SPEED_M_PER_S * dt, self.battery / BATTERY_PER_METER)
        self._enter_edge()
        while budget > 0 and self._can_drive():
            node = self.node_states[0]
            target_x, target_y = node["nodePosition"]["x"], node["nodePosition"]["y"]
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
            self._arrive()

        self._velocity = self._moved / dt
        if not self.node_states:
            self.mission_status = COMPLETED
        elif not self._can_drive():
            self.mission_status = WAITING  # decision point: the rest of the order is horizon
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
            # The order is kept (3.0 section 6.6.5.1: never clear the order on an error), so the robot
            # stays busy with it until a cancelOrder frees it.
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

    def _arrive(self) -> None:
        node = self.node_states.pop(0)
        if self.edge_states and self.edge_states[0]["sequenceId"] < node["sequenceId"]:
            edge = self.edge_states.pop(0)
            self._run_actions(self._edge_actions.get(edge["sequenceId"], []))
        self._traverse(node)

    def _traverse(self, node: dict) -> None:
        """The robot is at `node` (already removed from nodeStates): run its actions, enter the next edge."""
        self.last_node_id = node["nodeId"]
        self.last_node_sequence_id = node["sequenceId"]
        self._last_node_xy = (node["nodePosition"]["x"], node["nodePosition"]["y"])
        self._run_actions(self._node_actions.get(node["sequenceId"], []))
        self._enter_edge()

    def _enter_edge(self) -> None:
        """Edge actions start (RUNNING) when the edge is entered, i.e. its start node is traversed."""
        if self.edge_states and self.edge_states[0]["released"]:
            for action in self._states_of(self._edge_actions.get(self.edge_states[0]["sequenceId"], [])):
                if action["actionStatus"] == "WAITING":
                    action["actionStatus"] = "RUNNING"

    def _states_of(self, ids: list[str]) -> list[dict]:
        return [action for action in self.action_states if action["actionId"] in ids]

    def _run_actions(self, ids: list[str]) -> None:
        """Pick and drop happen instantly in the simulator; they change `loads`, or fail."""
        for action in self._states_of(ids):
            if action["actionStatus"] not in ("WAITING", "RUNNING"):
                continue  # e.g. an instant action refused for reusing this id
            if action["actionType"] == "pick" and self.loads:
                self._set_status(action, "FAILED", "pick failed: the robot already carries a load")
            elif action["actionType"] == "drop" and not self.loads:
                self._set_status(action, "FAILED", "drop failed: the robot carries no load")
            else:
                self.loads = (
                    [{"loadId": self._load_ids.get(action["actionId"], "")}] if action["actionType"] == "pick" else []
                )
                self._set_status(action, "FINISHED")

    def _set_status(self, action: dict, status: str, result: str | None = None) -> None:
        action["actionStatus"] = status
        if result:
            action["actionResult" if self.vda_major == "v3" else "resultDescription"] = result

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
            self.new_base_request,
            tuple(load["loadId"] for load in self.loads),
            tuple((action["actionId"], action["actionStatus"]) for action in self.instant_action_states),
            self.paused,
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
            "newBaseRequest": self.new_base_request,
            "loads": [dict(load) for load in self.loads],
            "driving": self._velocity > 0,
            "paused": self.paused,
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
            state["instantActionStates"] = [dict(action) for action in self.instant_action_states]
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
        instant = [
            {
                "actionType": action_type,
                "actionScopes": ["INSTANT"],
                # 3.0: cancelOrder may name the order to cancel.
                **(
                    {"actionParameters": [{"key": "orderId", "valueDataType": "STRING", "isOptional": True}]}
                    if v3 and action_type == "cancelOrder"
                    else {}
                ),
                # Instant actions finish at once, so they can neither be paused nor cancelled (strings: see above).
                **({"pauseAllowed": "false", "cancelAllowed": "false"} if v3 else {}),
            }
            for action_type in (INSTANT_ACTIONS_V3 if v3 else INSTANT_ACTIONS)
        ]
        features = {"optionalParameters": [], "mobileRobotActions" if v3 else "agvActions": pick_drop + instant}
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
