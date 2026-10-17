import copy
import json
import logging
import math

from simulator.instant import ID_IN_USE, InstantActions
from simulator.messages import (
    MALFORMED_KINDS,
    connection_message,
    factsheet_message,
    header,
    state_message,
    state_payload,
)
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
LOW_BATTERY = "LOW_BATTERY"
DISCONNECT = "DISCONNECT"
INVALID_PAYLOAD = "INVALID_PAYLOAD"
UNRESPONSIVE = "UNRESPONSIVE"
# Below this (and above 0) the state carries a batteryLow error (D-42); the robot keeps driving.
LOW_BATTERY_THRESHOLD = 20
DEFAULT_LOW_BATTERY_LEVEL = 15
# Bounds of the inject params, same as backend/app/failures.py and actunode-inject.schema.json.
DISCONNECT_MODES = ("broken", "offline")
DEFAULT_DISCONNECT_S = 10
MAX_DISCONNECT_S = 300
MAX_MALFORMED = 10
# The params each failure's inject takes; a clear takes none. Anything else is rejected, not silently defaulted.
FAILURE_PARAMS = {
    BLOCKED_PATH: (),
    LOW_BATTERY: ("level",),
    DISCONNECT: ("duration_s", "mode"),
    INVALID_PAYLOAD: ("kind", "count"),
    UNRESPONSIVE: ("duration_s",),
}
MAX_PENDING_MALFORMED = 10  # per robot; further requests are dropped (S-1)


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
        # DISCONNECT and INVALID_PAYLOAD only record their request here; the publisher acts on it from step().
        self.disconnect_requested: tuple[int, str] | None = None  # (duration_s, mode)
        # UNRESPONSIVE: duration_s requested here; the publisher starts it from step() and sets `unresponsive`.
        self.unresponsive_requested: int | None = None
        self.unresponsive = False
        self.malformed_requests: list[str] = []  # kinds, one malformed state published per tick
        # Set by the publisher while the link is down (or coming back): a DISCONNECT then makes no sense.
        self.link_down = False
        # Battery level before a LOW_BATTERY injection, restored by its clear.
        self._battery_before_injection: float | None = None
        # Loads the robot carries, as reported in `loads`.
        self.loads: list[dict] = []
        # Per sequenceId: the actions attached to a node (edge actions are rejected), and where the robot last stood.
        self._node_actions: dict[int, list[str]] = {}
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
        # An order or update that arrives is answered with a state, whatever happens to it (2.1 section 6.6, 3.0 6.1).
        self.state_requested = True
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
        is_update = order_id == self.order_id
        problem = check_order(order, self.robot_id, self.v, is_update)
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
        before = self._order_snapshot()
        try:
            return self._apply_update(order) if is_update else self._apply_new_order(order)
        except Exception:
            for name, value in before.items():
                setattr(self, name, value)
            raise

    # What applying an order or update can change; the snapshot copies only this (a deep copy of the whole robot
    # costs milliseconds per order, and the single sim thread serves every robot).
    _ORDER_FIELDS = (
        "mission_status",
        "order_id",
        "order_update_id",
        "last_node_id",
        "last_node_sequence_id",
        "_last_node_xy",
        "_last_order",
        "loads",
        "errors",
        "node_states",
        "edge_states",
        "action_states",
        "instant_action_states",
        "_node_actions",
        "_load_ids",
    )

    def _order_snapshot(self) -> dict:
        """The order fields as they are now. Actions are copied one level deeper: their status changes in place."""
        saved = {name: copy.copy(getattr(self, name)) for name in self._ORDER_FIELDS}
        for name in ("action_states", "instant_action_states"):
            saved[name] = [dict(action) for action in saved[name]]
        return saved

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

        params = command.get("params")
        params = params if isinstance(params, dict) else {}  # older backends send none
        if action not in ("inject", "clear"):
            return f"ignored unknown action {action!r}"
        if failure in FAILURE_PARAMS:
            allowed = FAILURE_PARAMS[failure] if action == "inject" else ()
            unknown = next((key for key in params if key not in allowed), None)
            if unknown is not None:
                return f"ignored {failure}: unknown param {unknown}"
        if failure == BLOCKED_PATH:
            if action == "inject":
                return "path blocked" if self.block_path() else f"ignored BLOCKED_PATH while {self.mission_status}"
            return "path cleared" if self.clear_blocked_path() else "ignored clear: not blocked"
        if failure == LOW_BATTERY:
            return self._low_battery(action, params)
        if failure in (DISCONNECT, INVALID_PAYLOAD, UNRESPONSIVE) and action == "clear":
            return f"ignored clear: {failure} cannot be cleared"
        if failure == DISCONNECT:
            return self._request_disconnect(params)
        if failure == INVALID_PAYLOAD:
            return self._request_malformed(params)
        if failure == UNRESPONSIVE:
            return self._request_unresponsive(params)
        return f"ignored unknown failure {failure!r}"

    @staticmethod
    def _int_param(params: dict, key: str, default: int, low: int, high: int) -> int | None:
        """The int param within [low, high], the default when absent, None when invalid (bool is not an int here)."""
        value = params.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            return None
        return value

    def _low_battery(self, action: str, params: dict) -> str:
        if action == "clear":
            if self._battery_before_injection is None:
                return "ignored clear: not injected"
            self.battery, self._battery_before_injection = self._battery_before_injection, None
            self._drop_empty_if_charged()
            self._sync_battery_low()
            return f"battery restored to {self.battery:g}%"
        level = self._int_param(params, "level", DEFAULT_LOW_BATTERY_LEVEL, 1, 99)
        if level is None:
            return "ignored LOW_BATTERY: level must be an integer from 1 to 99"
        if self._battery_before_injection is None:  # injecting twice keeps the first original level
            self._battery_before_injection = self.battery
        self.battery = float(level)
        self._drop_empty_if_charged()
        self._sync_battery_low()
        return f"battery set to {level}%"

    def _drop_empty_if_charged(self) -> None:
        """No FATAL batteryEmpty next to a battery above 0 (as in _charge). The mission stays FAILED:
        an order update resumes it, a cancelOrder frees the robot (D-33)."""
        if self.battery > 0:
            self._drop_errors("batteryEmpty")

    def _request_disconnect(self, params: dict) -> str:
        duration = self._int_param(params, "duration_s", DEFAULT_DISCONNECT_S, 1, MAX_DISCONNECT_S)
        mode = params.get("mode", "broken")
        if self.link_down or self.disconnect_requested is not None:
            return "ignored DISCONNECT: already disconnected"
        if self.unresponsive or self.unresponsive_requested is not None:
            return "ignored DISCONNECT: already unresponsive"
        if duration is None or mode not in DISCONNECT_MODES:
            return f"ignored DISCONNECT: duration_s 1-{MAX_DISCONNECT_S}, mode one of {list(DISCONNECT_MODES)}"
        self.disconnect_requested = (duration, mode)
        return f"disconnect for {duration} s ({mode})"

    def _request_unresponsive(self, params: dict) -> str:
        duration = self._int_param(params, "duration_s", DEFAULT_DISCONNECT_S, 1, MAX_DISCONNECT_S)
        if self.unresponsive or self.unresponsive_requested is not None:
            return "ignored UNRESPONSIVE: already unresponsive"
        if self.link_down or self.disconnect_requested is not None:
            return "ignored UNRESPONSIVE: already disconnected"
        if duration is None:
            return f"ignored UNRESPONSIVE: duration_s 1-{MAX_DISCONNECT_S}"
        self.unresponsive_requested = duration
        return f"unresponsive for {duration} s"

    def _request_malformed(self, params: dict) -> str:
        kind = params.get("kind")
        count = self._int_param(params, "count", 1, 1, MAX_MALFORMED)
        if kind not in MALFORMED_KINDS or count is None:
            return f"ignored INVALID_PAYLOAD: kind one of {list(MALFORMED_KINDS)}, count 1-{MAX_MALFORMED}"
        queued = min(count, MAX_PENDING_MALFORMED - len(self.malformed_requests))
        self.malformed_requests += [kind] * queued
        dropped = f" ({count - queued} dropped: at most {MAX_PENDING_MALFORMED} pending)" if queued < count else ""
        return f"{queued} malformed message(s) queued: {kind}{dropped}"

    def _sync_battery_low(self) -> None:
        """batteryLow while 0 < battery < threshold; batteryEmpty (FATAL) takes over at 0."""
        low = 0 < self.battery < LOW_BATTERY_THRESHOLD
        description = f"Battery low: {self.battery:.0f}%"
        existing = next((e for e in self.errors if e["errorType"] == "batteryLow"), None)
        if low and existing:
            existing["errorDescription"] = description  # the type is the event, so no extra state message
        elif low:
            self._add_error("batteryLow", description, [], level=self.v.battery_low_level)
        elif existing:
            self._drop_errors("batteryLow")

    def _sync_battery_empty(self) -> None:
        """batteryEmpty (FATAL) whenever the battery is at 0, wherever the robot stopped (at the last node or the
        decision point too, not only on the way to a node); removed again above 0."""
        has_error = any(e["errorType"] == "batteryEmpty" for e in self.errors)
        if self.battery > 0 and has_error:
            self._drop_errors("batteryEmpty")
        elif self.battery <= 0 and not has_error:
            references = [ref("orderId", self.order_id)] if self.order_id else []
            self._add_error(
                "batteryEmpty", f"Battery empty; stopped at ({self.x:.1f}, {self.y:.1f})", references, level="FATAL"
            )

    @property
    def injected_failures(self) -> list[str]:
        """The injected failures a clear command can end, for the state's `actunode` extension."""
        return [
            name
            for name, active in (
                (BLOCKED_PATH, self.mission_status == BLOCKED),
                (LOW_BATTERY, self._battery_before_injection is not None),
            )
            if active
        ]

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
        self._add_error(
            "pathBlocked", description, [reference, ref("orderId", self.order_id)], level=self.v.path_blocked_level
        )
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
        self._advance(dt)
        self._sync_battery_low()
        self._sync_battery_empty()

    def _advance(self, dt: float) -> None:
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
            self.edge_states.pop(0)
        self._traverse(node)

    def _traverse(self, node: dict) -> None:
        """The robot is at `node` (already removed from nodeStates): run its actions."""
        self.last_node_id = node["nodeId"]
        self.last_node_sequence_id = node["sequenceId"]
        self._last_node_xy = (node["nodePosition"]["x"], node["nodePosition"]["y"])
        self._run_actions(self._node_actions.pop(node["sequenceId"], []))

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

    def state_payload(self) -> str:
        return state_payload(self)

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
            tuple(
                (error["errorType"], tuple((r["referenceKey"], r["referenceValue"]) for r in error["errorReferences"]))
                for error in self.errors
            ),
            self.velocity > 0,
            self.order_id,
            self.order_update_id,
            self.new_base_request,
            tuple(load["loadId"] for load in self.loads),
            tuple((action["actionId"], action["actionStatus"]) for action in self.instant_action_states),
            self.paused,
            tuple(self.injected_failures),
        )
