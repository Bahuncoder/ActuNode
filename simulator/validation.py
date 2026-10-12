"""Pure order and instant action validation: no robot state, only the message and what it is checked against."""

from typing import NamedTuple

from simulator.protocol import (
    MAX_ACTIONS_PER_ORDER,
    MAX_EDGES_PER_ORDER,
    MAX_ID_LENGTH,
    MAX_NODES_PER_ORDER,
    SUPPORTED_ACTIONS,
    Reject,
    VersionProfile,
    clip,
)


class Problem(NamedTuple):
    """Why a message is refused: what is wrong, the offending field (if any), and the kind of rejection."""

    description: str
    field: str | None = None
    kind: Reject = Reject.MALFORMED


_Pair = tuple[str, str | None]  # (description, offending field): what the structural checks return


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    # abs() <= 1e300 is False for NaN and infinity, and compares huge ints (10**400) without overflowing.
    return isinstance(value, int | float) and not isinstance(value, bool) and abs(value) <= 1e300


def _too_long(value) -> bool:
    return isinstance(value, str) and len(value) > MAX_ID_LENGTH


def long_id(item: dict, keys: tuple[str, ...], path: str) -> _Pair | None:
    for key in keys:
        if _too_long(item.get(key)):
            return f"{path}.{key} is longer than {MAX_ID_LENGTH} characters", f"{path}.{key}"
    return None


def _is_deviation(value, ellipse: bool) -> bool:
    """3.0: ellipse {a, b, theta}; 2.1: radius in meters."""
    if ellipse:
        return isinstance(value, dict) and all(_is_number(value.get(key)) for key in ("a", "b", "theta"))
    return _is_number(value) and value >= 0


def check_parameters(parameters, path: str) -> _Pair | None:
    """actionParameters, when present: a list of objects with a string key (the value may be any JSON)."""
    if not isinstance(parameters, list):
        return f"{path} must be a list", path
    for i, parameter in enumerate(parameters):
        if not isinstance(parameter, dict) or not isinstance(parameter.get("key"), str):
            return f"{path}[{i}] must be an object with a string key", f"{path}[{i}]"
        if parameter["key"] == "loadId" and _too_long(parameter.get("value")):
            return f"{path}[{i}].value is longer than {MAX_ID_LENGTH} characters", f"{path}[{i}].value"
    return None


def check_actions(actions, path: str, parameters: bool = True) -> _Pair | None:
    if not isinstance(actions, list):
        return f"{path} must be a list", path
    for i, action in enumerate(actions):
        where = f"{path}[{i}]"
        if not isinstance(action, dict):
            return f"{where} must be an object", where
        for key in ("actionType", "actionId"):
            if not isinstance(action.get(key), str):
                return f"{where}.{key} must be a string", f"{where}.{key}"
        problem = long_id(action, ("actionType", "actionId"), where)
        if problem:
            return problem
        if parameters and "actionParameters" in action:
            problem = check_parameters(action["actionParameters"], f"{where}.actionParameters")
            if problem:
                return problem
    return None


def _check_position(position: dict, path: str, ellipse: bool) -> _Pair | None:
    for axis in ("x", "y"):
        if not _is_number(position.get(axis)):
            return f"{path}.{axis} must be a finite number", f"{path}.{axis}"
    if "mapId" in position and not isinstance(position["mapId"], str):
        return f"{path}.mapId must be a string", f"{path}.mapId"
    problem = long_id(position, ("mapId",), path)
    if problem:
        return problem
    if "allowedDeviationXY" in position and not _is_deviation(position["allowedDeviationXY"], ellipse):
        what = "an object {a, b, theta}" if ellipse else "a number"
        return f"{path}.allowedDeviationXY must be {what}", f"{path}.allowedDeviationXY"
    return None


def _check_node(node, path: str, ellipse: bool) -> _Pair | None:
    if not isinstance(node, dict):
        return f"{path} must be an object", path
    if not isinstance(node.get("nodeId"), str):
        return f"{path}.nodeId must be a string", f"{path}.nodeId"
    problem = long_id(node, ("nodeId",), path)
    if problem:
        return problem
    if not _is_int(node.get("sequenceId")):
        return f"{path}.sequenceId must be an integer", f"{path}.sequenceId"
    if "released" in node and not isinstance(node["released"], bool):
        return f"{path}.released must be a boolean", f"{path}.released"
    position = node.get("nodePosition")
    if not isinstance(position, dict):
        return f"node {node['nodeId']} has no nodePosition", f"{path}.nodePosition"
    problem = _check_position(position, f"{path}.nodePosition", ellipse)
    if problem:
        return problem
    return check_actions(node.get("actions", []), f"{path}.actions")


def _check_edge(edge, path: str) -> _Pair | None:
    if not isinstance(edge, dict):
        return f"{path} must be an object", path
    if not isinstance(edge.get("edgeId"), str):
        return f"{path}.edgeId must be a string", f"{path}.edgeId"
    problem = long_id(edge, ("edgeId", "startNodeId", "endNodeId"), path)
    if problem:
        return problem
    if not _is_int(edge.get("sequenceId")):
        return f"{path}.sequenceId must be an integer", f"{path}.sequenceId"
    if "released" in edge and not isinstance(edge["released"], bool):
        return f"{path}.released must be a boolean", f"{path}.released"
    for key in ("startNodeId", "endNodeId"):
        if key in edge and not isinstance(edge[key], str):
            return f"{path}.{key} must be a string", f"{path}.{key}"
    return check_actions(edge.get("actions", []), f"{path}.actions")


def count_actions(items: list[dict]) -> int:
    return sum(len(item.get("actions", [])) for item in items)


def check_size(nodes: int, edges: int, actions: int) -> _Pair | None:
    """An order holds at most so many nodes, edges and actions at a time: the state echoes all of them."""
    for name, count, limit in (
        ("nodes", nodes, MAX_NODES_PER_ORDER),
        ("edges", edges, MAX_EDGES_PER_ORDER),
        ("actions", actions, MAX_ACTIONS_PER_ORDER),
    ):
        if count > limit:
            return f"order has {count} {name}; at most {limit} are allowed", name
    return None


def _check_unique(nodes: list[dict], edges: list[dict]) -> _Pair | None:
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


def _check_header(order: dict, robot_id: str) -> _Pair | None:
    if order.get("serialNumber") != robot_id:
        return f"order is addressed to {clip(repr(order.get('serialNumber')))}, not {robot_id!r}", None
    if not order.get("orderId"):
        return "order has no orderId", "orderId"
    if not isinstance(order["orderId"], str):
        return "orderId must be a string", "orderId"
    if _too_long(order["orderId"]):
        return f"orderId is longer than {MAX_ID_LENGTH} characters", "orderId"
    if "orderUpdateId" in order and not _is_int(order["orderUpdateId"]):
        return "orderUpdateId must be an integer", "orderUpdateId"
    return None


def _check_structure(order: dict, robot_id: str, profile: VersionProfile) -> _Pair | None:
    problem = _check_header(order, robot_id)
    if problem:
        return problem
    nodes = order.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return "order has no nodes", "nodes"
    for i, node in enumerate(nodes):
        problem = _check_node(node, f"nodes[{i}]", profile.deviation_is_ellipse)
        if problem:
            return problem
    edges = order.get("edges", [])
    if not isinstance(edges, list):
        return "edges must be a list", "edges"
    for i, edge in enumerate(edges):
        problem = _check_edge(edge, f"edges[{i}]")
        if problem:
            return problem
    return check_size(len(nodes), len(edges), count_actions(nodes) + count_actions(edges)) or _check_unique(
        nodes, edges
    )


def _check_action_types(order: dict) -> _Pair | None:
    """Only pick and drop are supported; the error names the field (3.0 section 6.1.4)."""
    for kind in ("nodes", "edges"):
        for i, item in enumerate(order.get(kind, [])):
            for j, action in enumerate(item.get("actions", [])):
                if action["actionType"] not in SUPPORTED_ACTIONS:
                    return f"unsupported action type {action['actionType']!r}", f"{kind}[{i}].actions[{j}].actionType"
    return None


def check_order(order: dict, robot_id: str, profile: VersionProfile) -> Problem | None:
    """The first thing wrong with an order message (structure, then action types), else None."""
    pair = _check_structure(order, robot_id, profile)
    if pair:
        return Problem(*pair)
    pair = _check_action_types(order)
    return Problem(*pair, kind=Reject.ACTION) if pair else None
