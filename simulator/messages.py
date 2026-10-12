"""The VDA 5050 messages a robot publishes, as functions of the robot (Robot's methods of the same names call these)."""

import json
import math

from simulator.protocol import (
    MANUFACTURER,
    MAP_ID,
    MAX_ID_LENGTH,
    MAX_STATE_BYTES,
    SPEED_M_PER_S,
    SUPPORTED_ACTIONS,
    utc_timestamp,
)

# The schemas require every factsheet section, so numbers the simulator has no model for are nominal.
NOMINAL_BODY_M = {"width": 0.6, "length": 0.8}
NOMINAL_HEIGHT_M = 0.3
NOMINAL_ACCELERATION_M_S2 = 10.0  # no acceleration model: speed changes instantly, so this is a stand-in
NOMINAL_MAX_LOAD_MASS_KG = 100  # no mass model, but the robot does carry loads
NOMINAL_MIN_INTERVAL_S = 0.1


def header(robot, topic_name: str) -> dict:
    """Fields every VDA 5050 message starts with."""
    return {
        "headerId": robot.next_header_id(topic_name),
        "timestamp": utc_timestamp(),
        "version": robot.v.protocol_version,
        "manufacturer": MANUFACTURER,
        "serialNumber": robot.robot_id,
    }


def state_message(robot) -> dict:
    """VDA 5050 `state` message in the robot's version. ActuNode-specific fields go under `actunode`."""
    v = robot.v
    # Rounding can push pi up to 3.142; the spec range is [-pi, pi].
    theta = max(-math.pi, min(math.pi, round(robot.theta, 3)))
    position = {"x": round(robot.x, 3), "y": round(robot.y, 3), "theta": theta, "mapId": MAP_ID, **v.position_extra}
    state = {
        **header(robot, "state"),
        "orderId": robot.order_id,
        "orderUpdateId": robot.order_update_id,
        "lastNodeId": robot.last_node_id,
        "lastNodeSequenceId": robot.last_node_sequence_id,
        "nodeStates": [{**node, "nodePosition": dict(node["nodePosition"])} for node in robot.node_states],
        "edgeStates": [dict(edge) for edge in robot.edge_states],
        "newBaseRequest": robot.new_base_request,
        "loads": [dict(load) for load in robot.loads],
        "driving": robot.velocity > 0,
        "paused": robot.paused,
        "operatingMode": "AUTOMATIC",
        "velocity": {"vx": round(robot.velocity, 3), "vy": 0.0, "omega": 0.0},
        "errors": [dict(error) for error in robot.errors],
        "actunode": {"missionStatus": robot.mission_status},
        v.position_key: position,
        v.battery_key: {v.battery_charge_key: round(robot.battery, 1), "charging": robot.charging},
        "safetyState": dict(v.safety_state),
    }
    _put_action_states(robot, state)
    # Final guard: whatever else grew (the ids are bounded, the counts are not all), the state must stay
    # below the broker's packet limit. Drop the oldest finished instant action states until it fits.
    while len(json.dumps(state)) > MAX_STATE_BYTES and robot.drop_oldest_done_instant_state():
        _put_action_states(robot, state)
    return state


def _put_action_states(robot, state: dict) -> None:
    orders = [dict(action) for action in robot.action_states]
    instants = [dict(action) for action in robot.instant_action_states]
    if robot.v.instant_states_separate:
        state["actionStates"], state["instantActionStates"] = orders, instants
    else:  # 2.1 has no instantActionStates: instant actions are listed among the order's action states
        state["actionStates"] = orders + instants


def factsheet_message(robot) -> dict:
    """VDA 5050 `factsheet` in the robot's version. Only what the simulator really does; one builder, the
    version's field names come from its profile."""
    v = robot.v
    n = v.factsheet
    # pick and drop at nodes; the backend tags the load with an optional loadId.
    pick_drop = [
        {
            "actionType": action_type,
            "actionScopes": ["NODE"],
            "actionParameters": [{"key": "loadId", "valueDataType": "STRING", "isOptional": True}],
            **v.action_flags,
        }
        for action_type in SUPPORTED_ACTIONS
    ]
    order_parameter = {"actionParameters": [{"key": "orderId", "valueDataType": "STRING", "isOptional": True}]}
    instant = [
        {
            "actionType": action_type,
            "actionScopes": ["INSTANT"],
            **(order_parameter if v.cancel_has_order_param and action_type == "cancelOrder" else {}),
            # Instant actions finish at once, so they can neither be paused nor cancelled.
            **v.action_flags,
        }
        for action_type in v.instant_actions
    ]
    return {
        **header(robot, "factsheet"),
        "typeSpecification": {
            "seriesName": "ActuNode simulated AMR",
            n["kinematic"]: v.kinematics,
            n["class"]: "CARRIER",
            n["max_load_mass"]: NOMINAL_MAX_LOAD_MASS_KG,
            "localizationTypes": ["NATURAL"],
            "navigationTypes": ["VIRTUAL_LINE_GUIDED"],
            **v.type_extra,
        },
        "physicalParameters": {
            n["speed_min"]: 0.0,
            n["speed_max"]: SPEED_M_PER_S,
            n["acceleration"]: NOMINAL_ACCELERATION_M_S2,
            n["deceleration"]: NOMINAL_ACCELERATION_M_S2,
            n["height_min"]: NOMINAL_HEIGHT_M,
            n["height_max"]: NOMINAL_HEIGHT_M,
            **NOMINAL_BODY_M,
        },
        "protocolLimits": {
            n["string_lengths"]: {n["id_length"]: MAX_ID_LENGTH, n["load_id_length"]: MAX_ID_LENGTH},
            n["array_lengths"]: {},
            "timing": {n["order_interval"]: NOMINAL_MIN_INTERVAL_S, n["state_interval"]: NOMINAL_MIN_INTERVAL_S},
        },
        "protocolFeatures": {"optionalParameters": [], n["actions"]: pick_drop + instant},
        n["geometry"]: {},
        "loadSpecification": {},
    }


def connection_message(robot, connection_state: str) -> dict:
    """VDA 5050 `connection` message: ONLINE, OFFLINE or CONNECTIONBROKEN (CONNECTION_BROKEN in 3.0)."""
    if connection_state == "CONNECTIONBROKEN":
        connection_state = robot.v.connection_broken
    return {**header(robot, "connection"), "connectionState": connection_state}
