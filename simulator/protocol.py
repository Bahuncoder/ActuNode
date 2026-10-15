"""What the two VDA 5050 versions (2.1, 3.0) call things, plus the protocol constants and limits the simulator shares.

Everything that differs between the versions lives in one VersionProfile per version; the rest of the
simulator reads the profile instead of asking which version it speaks.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

MANUFACTURER = "ActuNode"
# Topic major version -> protocol version a robot reports (D-15). 2.1 is the default.
VDA_VERSIONS = {"v2": "2.1.0", "v3": "3.0.0"}
MAP_ID = "warehouse"
SPEED_M_PER_S = 1.0

# Mission state machine (actunode.missionStatus; the backend's validator.py ALLOWED_TRANSITIONS must agree):
#   IDLE -> ACCEPTED -> MOVING -> COMPLETED
# An order with a horizon stops at its last released node: MOVING -> WAITING until an order update releases more
# (-> MOVING again) or ends the order (-> COMPLETED). An update for a COMPLETED order stitches at its last node
# (COMPLETED -> ACCEPTED, or -> WAITING when the new base is not released yet).
# Failure injection can put a robot on a route into BLOCKED until cleared (-> MOVING).
# An empty battery ends the mission in FAILED; the order is kept: a later accepted update resumes it
# (FAILED -> MOVING) or a cancelOrder frees the robot.
# cancelOrder stops the robot at once (ACCEPTED, MOVING, WAITING, BLOCKED or FAILED -> CANCELLED); only a new
# order is accepted after that (CANCELLED -> ACCEPTED).
IDLE = "IDLE"
ACCEPTED = "ACCEPTED"
MOVING = "MOVING"
COMPLETED = "COMPLETED"
BLOCKED = "BLOCKED"
WAITING = "WAITING"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

# actionStatus groups: finished for good / still to do.
DONE = frozenset({"FINISHED", "FAILED"})
PENDING = frozenset({"WAITING", "RUNNING"})

# The only action types the simulator performs in orders.
SUPPORTED_ACTIONS = ("pick", "drop")
# Instant actions the simulator performs (2.1 section 6.8.1, 3.0 section 6.2.1); clearInstantActions is 3.0 only.
INSTANT_ACTIONS = ("cancelOrder", "startPause", "stopPause", "stateRequest", "factsheetRequest")
INSTANT_ACTIONS_V3 = (*INSTANT_ACTIONS, "clearInstantActions")

# Instant action states kept. 3.0 allows an URGENT INSTANT_ACTION_STATES_FULL error when the list grows too
# long; the simulator drops the oldest finished/failed one instead, so it never gets there.
MAX_INSTANT_ACTION_STATES = 50
# One instantActions message is handled up to this many actions: more would make the state (every failed one
# gets a state) outgrow the broker's max_packet_size.
MAX_INSTANT_ACTIONS_PER_MESSAGE = 50
# Longest id-like string (orderId, nodeId, edgeId, actionId, actionType, mapId, loadId) the robot stores or echoes;
# advertised in the factsheet. Unbounded ids would let one message outgrow the broker's 256 KiB max_packet_size.
MAX_ID_LENGTH = 128
# What one order may hold at a time (nodes, edges and actions across base and horizon, updates included). The
# state echoes all of it, so with MAX_ID_LENGTH ids the worst case is about 180 KiB: below MAX_STATE_BYTES, which
# leaves room for the instant action states that state_message() can then always trim to fit the broker.
MAX_NODES_PER_ORDER = 300
MAX_EDGES_PER_ORDER = 300
MAX_ACTIONS_PER_ORDER = 300
# state_message() drops old finished instant action states above this size (the broker allows 256 KiB).
MAX_STATE_BYTES = 200 * 1024
# Untrusted MQTT payload limits, same as backend/app/live.py (D-31).
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_DEPTH = 32


class Reject(Enum):
    """Why an order was rejected (D-35). Each version names the error (VersionProfile.order_errors)."""

    MALFORMED = "malformed"
    ACTION = "action"
    ACTIVE = "active"
    RANGE = "range"
    OUTDATED = "outdated"
    SAME = "same"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    STITCH = "stitch"
    OTHER = "other"


@dataclass(frozen=True)
class VersionProfile:
    major: str
    protocol_version: str
    # Where a version names no error the closest 2.1 name is reused; the stitch case names none in either version.
    order_errors: dict[Reject, str]
    # NO_ORDER_TO_CANCEL stays "until new order is accepted" (3.0 section 6.6.7), like a rejection.
    no_order_to_cancel: str
    invalid_instant_action: str | None  # 2.1 names no error for a failed instant action: only its state reports it
    result_key: str  # the actionState field describing the outcome
    instant_actions: tuple[str, ...]
    connection_broken: str
    # Error levels (D-42): 2.1 has WARNING and FATAL only; 3.0 adds URGENT (low battery) and CRITICAL (cannot continue).
    path_blocked_level: str
    battery_low_level: str
    deviation_is_ellipse: bool  # allowedDeviationXY: 3.0 {a, b, theta}, 2.1 a radius in meters
    edges_have_endpoints: bool  # 2.1 edges carry startNodeId and endNodeId; 3.0 edges do not
    cancel_has_order_param: bool  # 3.0 cancelOrder may name the order to cancel
    # 3.0 reports SAME_ORDER_UPDATE_ID for a reused orderUpdateId with other content; 2.1 ignores any such message.
    strict_same_update_id: bool
    # 3.0 Figure 8 asks "follows cancel" (step 7) before "same orderUpdateId" (step 8). 2.1 still ignores a repeat
    # of the last update (a duplicate delivery) even after a cancel.
    cancel_checked_before_same_id: bool
    instant_states_separate: bool  # 3.0 reports instantActionStates; 2.1 lists them among actionStates
    # 2.1: action states are removed upon a new order, except running instant actions. 3.0 keeps instant actions apart.
    new_order_clears_instant_states: bool
    position_key: str
    position_extra: dict  # what the position object adds to x, y, theta, mapId
    battery_key: str
    battery_charge_key: str
    safety_state: dict
    # factsheet field names, by what they hold (see messages.factsheet_message), and the kinematics values
    factsheet: dict[str, str]
    kinematics: str
    type_extra: dict  # typeSpecification fields only this version has
    # The 3.0.0 text says boolean, but the official schema types these two as string.
    action_flags: dict


R = Reject
_ERRORS_V2 = {
    R.MALFORMED: "validationError",
    R.ACTION: "orderError",
    R.ACTIVE: "orderError",
    R.RANGE: "orderError",
    R.OUTDATED: "orderUpdateError",
    R.SAME: "orderUpdateError",
    R.CANCELLED: "orderUpdateError",
    R.UNAVAILABLE: "orderUpdateError",
    R.STITCH: "orderUpdateError",
    R.OTHER: "orderError",
}
_ERRORS_V3 = {
    R.MALFORMED: "VALIDATION_FAILURE",
    R.ACTION: "INVALID_ORDER_ACTION",
    R.ACTIVE: "OTHER_ORDER_ACTIVE",
    R.RANGE: "START_NODE_OUT_OF_RANGE",
    R.OUTDATED: "OUTDATED_ORDER_UPDATE",
    R.SAME: "SAME_ORDER_UPDATE_ID",
    R.CANCELLED: "ORDER_UPDATE_FOLLOWING_CANCEL",
    # An update while the battery is empty: 3.0 names no error for it; this is the closest ("until operating
    # mode allows for new orders"). 2.1 has orderUpdateError for any failed update.
    R.UNAVAILABLE: "MOBILE_ROBOT_NOT_AVAILABLE",
    R.STITCH: "VALIDATION_FAILURE",
    R.OTHER: "MOBILE_ROBOT_NOT_AVAILABLE",  # an empty battery on a new order: the closest 3.0 name
}

_FACTSHEET_V2 = {
    "actions": "agvActions",
    "kinematic": "agvKinematic",
    "class": "agvClass",
    "max_load_mass": "maxLoadMass",
    "speed_min": "speedMin",
    "speed_max": "speedMax",
    "acceleration": "accelerationMax",
    "deceleration": "decelerationMax",
    "height_min": "heightMin",
    "height_max": "heightMax",
    "string_lengths": "maxStringLens",
    "id_length": "idLen",
    "load_id_length": "loadIdLen",
    "array_lengths": "maxArrayLens",
    "order_interval": "minOrderInterval",
    "state_interval": "minStateInterval",
    "geometry": "agvGeometry",
}
_FACTSHEET_V3 = {
    "actions": "mobileRobotActions",
    "kinematic": "mobileRobotKinematic",
    "class": "mobileRobotClass",
    "max_load_mass": "maximumLoadMass",
    "speed_min": "minimumSpeed",
    "speed_max": "maximumSpeed",
    "acceleration": "maximumAcceleration",
    "deceleration": "maximumDeceleration",
    "height_min": "minimumHeight",
    "height_max": "maximumHeight",
    "string_lengths": "maximumStringLengths",
    "id_length": "maximumIdLength",
    "load_id_length": "maximumLoadIdLength",
    "array_lengths": "maximumArrayLengths",
    "order_interval": "minimumOrderInterval",
    "state_interval": "minimumStateInterval",
    "geometry": "mobileRobotGeometry",
}

PROFILES = {
    "v2": VersionProfile(
        major="v2",
        protocol_version=VDA_VERSIONS["v2"],
        order_errors=_ERRORS_V2,
        no_order_to_cancel="noOrderToCancel",
        invalid_instant_action=None,
        result_key="resultDescription",
        instant_actions=INSTANT_ACTIONS,
        connection_broken="CONNECTIONBROKEN",
        path_blocked_level="WARNING",
        battery_low_level="WARNING",
        deviation_is_ellipse=False,
        edges_have_endpoints=True,
        cancel_has_order_param=False,
        strict_same_update_id=False,
        cancel_checked_before_same_id=False,
        instant_states_separate=False,
        new_order_clears_instant_states=True,
        position_key="agvPosition",
        position_extra={"positionInitialized": True},
        battery_key="batteryState",
        battery_charge_key="batteryCharge",
        safety_state={"eStop": "NONE", "fieldViolation": False},
        factsheet=_FACTSHEET_V2,
        # A point robot that turns to face its heading: the closest allowed kinematics is DIFF.
        kinematics="DIFF",
        type_extra={},
        action_flags={},
    ),
    "v3": VersionProfile(
        major="v3",
        protocol_version=VDA_VERSIONS["v3"],
        order_errors=_ERRORS_V3,
        no_order_to_cancel="NO_ORDER_TO_CANCEL",
        invalid_instant_action="INVALID_INSTANT_ACTION",
        result_key="actionResult",
        instant_actions=INSTANT_ACTIONS_V3,
        connection_broken="CONNECTION_BROKEN",
        path_blocked_level="CRITICAL",
        battery_low_level="URGENT",
        deviation_is_ellipse=True,
        edges_have_endpoints=False,
        cancel_has_order_param=True,
        strict_same_update_id=True,
        cancel_checked_before_same_id=True,
        instant_states_separate=True,
        new_order_clears_instant_states=False,
        position_key="mobileRobotPosition",
        position_extra={"localized": True},
        battery_key="powerSupply",
        battery_charge_key="stateOfCharge",
        safety_state={"activeEmergencyStop": "NONE", "fieldViolation": False},
        factsheet=_FACTSHEET_V3,
        kinematics="DIFFERENTIAL",
        # The schema requires mobileRobotKinematic but only defines mobileRobotKinematics: send both.
        type_extra={"mobileRobotKinematics": "DIFFERENTIAL"},
        action_flags={"pauseAllowed": "false", "cancelAllowed": "false"},
    ),
}
# Errors that stay until a new order (or update) is accepted: every version's rejection and no-order-to-cancel names.
REJECTION_TYPES = {
    name for profile in PROFILES.values() for name in (*profile.order_errors.values(), profile.no_order_to_cancel)
}


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clip(text: str, limit: int = MAX_ID_LENGTH) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def ref(key: str, value: str) -> dict:
    """An errorReference."""
    return {"referenceKey": key, "referenceValue": value}


def parse(payload: bytes) -> tuple[object, str | None]:
    """(body, None) or (None, why it was rejected). Mirrors backend/app/live.py parse_payload (D-31)."""

    def reject_constant(name):
        raise ValueError(f"{name} is not allowed")

    if len(payload) > MAX_PAYLOAD_BYTES:
        return None, f"payload is larger than {MAX_PAYLOAD_BYTES} bytes"
    try:
        body = json.loads(payload, parse_constant=reject_constant)
    except RecursionError:
        return None, "JSON is nested too deeply"
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError too
        return None, f"not valid JSON: {clip(str(exc))}"
    # Iterative: recursion is what deep payloads attack.
    level, depth = ([body] if isinstance(body, dict | list) else []), 1
    while level:
        if depth > MAX_DEPTH:
            return None, f"JSON is nested deeper than {MAX_DEPTH} levels"
        level = [c for i in level for c in (i.values() if isinstance(i, dict) else i) if isinstance(c, dict | list)]
        depth += 1
    return body, None
