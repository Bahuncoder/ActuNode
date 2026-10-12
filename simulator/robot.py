import copy
import json
import logging
import math

from simulator.instant import ID_IN_USE, InstantActions
from simulator.messages import connection_message, factsheet_message, header, state_message
from simulator.orders import OrderBook
from simulator.protocol import (
    ACCEPTED,
    BLOCKED,
    CANCELLED,
    COMPLETED,
    DONE,
    FAILED,
    IDLE,
    INSTANT_ACTIONS,
    INSTANT_ACTIONS_V3,
    MANUFACTURER,
    MAX_DEPTH,
    MAX_ID_LENGTH,
    MAX_INSTANT_ACTION_STATES,
    MAX_INSTANT_ACTIONS_PER_MESSAGE,
    MAX_PAYLOAD_BYTES,
    MAX_STATE_BYTES,
    MOVING,
    PENDING,
    PROFILES,
    REJECTION_TYPES,
    SPEED_M_PER_S,
    SUPPORTED_ACTIONS,
    VDA_VERSIONS,
    WAITING,
    Reject,
    clip,
    parse,
    ref,
)
from simulator.validation import Problem, check_order

log = logging.getLogger(__name__)

# The mission state machine is described in protocol.py. Names other modules and tests import from here:
__all__ = [
    "ACCEPTED",
    "BLOCKED",
    "CANCELLED",
    "COMPLETED",
    "FAILED",
    "ID_IN_USE",
    "IDLE",
    "INSTANT_ACTIONS",
    "INSTANT_ACTIONS_V3",
    "MANUFACTURER",
    "MAX_DEPTH",
    "MAX_ID_LENGTH",
    "MAX_INSTANT_ACTIONS_PER_MESSAGE",
    "MAX_INSTANT_ACTION_STATES",
    "MAX_PAYLOAD_BYTES",
    "MAX_STATE_BYTES",
    "MOVING",
    "REJECTION_TYPES",
    "SUPPORTED_ACTIONS",
    "VDA_VERSIONS",
    "WAITING",
    "Robot",
]

BATTERY_PER_METER = 0.2
# (x_min, y_min, x_max, y_max) of the warehouse map's charging zone, same as
# frontend/src/WarehouseMap.tsx and backend/app/warehouse.py.
CHARGING_AREA = (0.0, 0.0, 12.0, 4.0)
# Overflow parking zone, same (x_min, y_min, x_max, y_max) form. Both areas must match the "charging" and
# "parking" entries of backend/app/warehouse.py ZONES (checked by simulator/tests/test_main.py).
# Robots parked here do not charge: charging stays limited to CHARGING_AREA (D-33).
PARKING_AREA = (0.0, 5.0, 8.5, 10.5)
# % per second; fast so a demo robot is full again within two minutes.
CHARGE_PER_S = 1.0

BLOCKED_PATH = "BLOCKED_PATH"


class Robot(OrderBook, InstantActions):
    def __init__(self, robot_id: str, x: float = 0.0, y: float = 0.0, vda_major: str = "v2"):
        if vda_major not in PROFILES:
            raise ValueError(f"unsupported VDA 5050 major version {vda_major!r}; use one of {list(PROFILES)}")
        self.robot_id = robot_id
        self.vda_major = vda_major
        self.v = PROFILES[vda_major]

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
        # Instant action states, for both versions; state_message() decides where each version reports them.
        self.instant_action_states: list[dict] = []
        # startPause / stopPause (both versions report it as `paused`).
        self.paused = False
        # Set by factsheetRequest; the main loop publishes the factsheet and resets it.
        self.factsheet_requested = False
        # Set by stateRequest; the main loop publishes the state and resets it.
        self.state_requested = False
        # Loads the robot carries, as reported in `loads`.
        self.loads: list[dict] = []
        # Per sequenceId: the actions attached to a node/edge, and where the robot last stood.
        self._node_actions: dict[int, list[str]] = {}
        self._edge_actions: dict[int, list[str]] = {}
        self._load_ids: dict[str, str] = {}
        self._last_node_xy = (x, y)
        # The last order/update accepted, without headerId and timestamp, to recognise duplicates.
        self._last_order: dict = {}

        self.errors: list[dict] = []
        # Speed over the last update (m/s); 0 at standstill, so `driving` is only true when the robot moved.
        self.velocity = 0.0
        self._moved = 0.0
        # VDA 5050: headerId counts up per topic, starting at 1.
        self._header_ids: dict[str, int] = {}

    @property
    def busy(self) -> bool:
        """Working on an order: it neither charges nor takes a new one."""
        return self.mission_status in (ACCEPTED, MOVING, BLOCKED, WAITING)

    @property
    def cancelled(self) -> bool:
        """cancelOrder stopped the order: further updates of it are rejected."""
        return self.mission_status == CANCELLED

    @property
    def idle(self) -> bool:
        """VDA 5050 (2.1 section 6.6, 3.0 section 6.1): nothing left to traverse and every action done."""
        return (
            not self.node_states and not self.edge_states and all(a["actionStatus"] in DONE for a in self.action_states)
        )

    # --- Orders -----------------------------------------------------------

    def handle_order_payload(self, payload: bytes) -> bool:
        """Accept or reject a raw order message. Rejections are reported in `errors`."""
        order, why = parse(payload)
        if why:
            self._reject("", f"order rejected: {why}")
            return False
        if not isinstance(order, dict):
            self._reject("", "order must be a JSON object")
            return False
        return self.accept_order(order)

    def accept_order(self, order: dict) -> bool:
        """Validate, then start a new order or apply an order update. Nothing is mutated before validation passes."""
        order_id = str(order.get("orderId", ""))  # _reject clips it
        problem = check_order(order, self.robot_id, self.v)
        is_update = not problem and order_id == self.order_id
        # NOTE: a new order with orderUpdateId > 0 is accepted. 3.0 section 6.1.2 Figure 8 step 4 asks "Is
        # orderUpdateId 0?" (2.1 Figure 8 has no such step), but the outcome is only in the figure, not in the text.
        problem = problem or (self._check_update_ids(order) if is_update else None)
        if problem:
            self._reject(order_id, *problem)
            return False
        if is_update and order.get("orderUpdateId", 0) == self.order_update_id:
            return True  # a duplicate (the same content, or any content in 2.1): ignored
        if self.battery <= 0:
            # An update to a stopped order gets the "robot not available" error (see VersionProfile.order_errors).
            self._reject(
                order_id, "battery is empty; robot cannot drive", kind=Reject.UNAVAILABLE if is_update else Reject.OTHER
            )
            return False
        # Atomic: if anything unexpected fails half way, the robot stays exactly as it was.
        before = copy.deepcopy(self.__dict__)
        try:
            return self._apply_update(order) if is_update else self._apply_new_order(order)
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(before)
            raise

    def _check_update_ids(self, order: dict) -> Problem | None:
        """Figure 8 for an update of the current order (2.1 section 6.6.2, 3.0 section 6.1.2): outdated, after a
        cancel, or a reused orderUpdateId with other content. None for the rest, duplicates included."""
        update_id = order.get("orderUpdateId", 0)
        if update_id < self.order_update_id:
            return Problem(f"orderUpdateId {update_id} is older than {self.order_update_id}", kind=Reject.OUTDATED)
        if self.cancelled and (update_id > self.order_update_id or self.v.cancel_checked_before_same_id):
            return Problem("order update for a cancelled order", kind=Reject.CANCELLED)
        if (
            update_id == self.order_update_id
            and self.v.strict_same_update_id
            and self._comparable(order) != self._last_order
        ):
            return Problem(f"orderUpdateId {update_id} was already used with other content", kind=Reject.SAME)
        return None

    @staticmethod
    def _comparable(order: dict) -> dict:
        return {key: value for key, value in order.items() if key not in ("headerId", "timestamp")}

    # --- Errors -----------------------------------------------------------

    def _reject(
        self, order_id: str, description: str, field: str | None = None, kind: Reject = Reject.MALFORMED
    ) -> None:
        # Replace an earlier rejection, but keep other errors (e.g. pathBlocked).
        self._clear_rejections()
        references = [ref("orderId", clip(order_id))] if order_id else []
        if field:
            references.append(ref("field", clip(field)))
        self._add_error(self.v.order_errors[kind], clip(description, 4 * MAX_ID_LENGTH), references)

    def _add_error(self, error_type: str, description: str, references: list[dict], level: str = "WARNING") -> None:
        self.errors.append(
            {
                "errorType": error_type,
                "errorLevel": level,
                "errorDescription": description,
                "errorReferences": references,
            }
        )

    def _clear_rejections(self) -> None:
        """Rejections stay until a new order (or update) is accepted (2.1 section 6.6, 3.0 section 6.6.5.4)."""
        self.errors = [error for error in self.errors if error["errorType"] not in REJECTION_TYPES]

    def _drop_errors(self, error_type: str) -> bool:
        """Remove errors of this type; True if there were any."""
        kept = [error for error in self.errors if error["errorType"] != error_type]
        removed = len(kept) != len(self.errors)
        self.errors = kept
        return removed

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

        if self.edge_states and self.edge_states[0]["sequenceId"] < self.node_states[0]["sequenceId"]:
            reference = ref("edgeId", self.edge_states[0]["edgeId"])
            description = f"Path blocked on edge {self.edge_states[0]['edgeId']}"
        else:
            reference = ref("nodeId", self.node_states[0]["nodeId"])
            description = f"Path blocked on the way to {self.node_states[0]['nodeId']}"

        self._drop_errors("pathBlocked")
        self._add_error("pathBlocked", description, [reference, ref("orderId", self.order_id)])
        self.mission_status = BLOCKED
        self.velocity = 0.0
        return True

    def clear_blocked_path(self) -> bool:
        if self.mission_status != BLOCKED:
            return False
        self._drop_errors("pathBlocked")
        self.mission_status = MOVING
        return True

    # --- Simulation -------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance the simulation by `dt` seconds."""
        self._moved = 0.0
        self.velocity = 0.0
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
        self._drive(min(SPEED_M_PER_S * dt, self.battery / BATTERY_PER_METER))
        self.velocity = self._moved / dt
        if not self.node_states:
            self.mission_status = COMPLETED
        elif not self._can_drive():
            self.mission_status = WAITING  # decision point: the rest of the order is horizon
        elif self.battery <= 0:
            self._fail_battery_empty()
        if self.mission_status != MOVING:
            self.velocity = 0.0  # arrived or stopped: standing still

    def _drive(self, budget: float) -> None:
        """Move up to `budget` meters along the released nodes."""
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
        self._add_error(
            "batteryEmpty",
            f"Battery empty; stopped at ({self.x:.1f}, {self.y:.1f}) on the way to {next_node}",
            [ref("nodeId", next_node), ref("orderId", self.order_id)],
            level="FATAL",
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
            if action["actionStatus"] not in PENDING:
                continue
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
            action[self.v.result_key] = result

    def _drain(self, meters: float) -> None:
        self._moved += meters
        remaining = self.battery - meters * BATTERY_PER_METER
        # Snap float residue (e.g. 1e-17) to exactly empty.
        self.battery = remaining if remaining > 1e-9 else 0.0

    def status(self) -> None:
        """One line for the offline demo (main.py)."""
        print(f"{self.robot_id} | {self.mission_status} | x={self.x:.1f} y={self.y:.1f} | battery={self.battery:.1f}%")

    # --- Messages ---------------------------------------------------------

    def next_header_id(self, topic_name: str) -> int:
        self._header_ids[topic_name] = self._header_ids.get(topic_name, 0) + 1
        return self._header_ids[topic_name]

    def header(self, topic_name: str) -> dict:
        return header(self, topic_name)

    def state_message(self) -> dict:
        return state_message(self)

    def factsheet_message(self) -> dict:
        return factsheet_message(self)

    def connection_message(self, connection_state: str) -> dict:
        return connection_message(self, connection_state)

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
            self.velocity > 0,
            self.order_id,
            self.order_update_id,
            self.new_base_request,
            tuple(load["loadId"] for load in self.loads),
            tuple((action["actionId"], action["actionStatus"]) for action in self.instant_action_states),
            self.paused,
        )
