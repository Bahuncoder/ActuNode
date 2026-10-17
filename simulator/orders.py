"""Applying an accepted order: start it, or stitch an update at the decision point (2.1 6.6.2, 3.0 6.1.2).

A mixin of Robot: it edits the order state the robot holds (nodeStates, edgeStates, actionStates).
"""

import math

from simulator.protocol import ACCEPTED, COMPLETED, FAILED, MAP_ID, MOVING, WAITING, Reject
from simulator.validation import Problem, check_size, count_actions

# A first node within this distance of the robot is reachable when the order names no allowedDeviationXY.
DEFAULT_TOLERANCE_M = 0.25
# newBaseRequest is true when the decision point is this close (m).
NEW_BASE_DISTANCE_M = 1.0


class OrderBook:
    def _apply_new_order(self, order: dict) -> bool:
        if not self.idle:
            self._reject(order["orderId"], f"robot is busy with order {self.order_id}", kind=Reject.ACTIVE)
            return False
        nodes = sorted(order["nodes"], key=lambda node: node["sequenceId"])
        if not self._reachable(nodes[0]["nodePosition"]):
            self._reject(
                order["orderId"],
                f"first node {nodes[0]['nodeId']} is out of range of ({self.x:.1f}, {self.y:.1f})",
                "nodes[0].nodePosition",
                kind=Reject.RANGE,
            )
            return False

        self.order_id = order["orderId"]
        self.order_update_id = order.get("orderUpdateId", 0)
        self.node_states = []
        self.edge_states = []
        self.action_states = []
        if self.v.new_order_clears_instant_states:
            self.instant_action_states = [a for a in self.instant_action_states if a["actionStatus"] == "RUNNING"]
        self._node_actions = {}
        self._load_ids = {}
        self._add_to_order(nodes, sorted(order.get("edges", []), key=lambda edge: edge["sequenceId"]))
        self._last_order = self._comparable(order)
        self._clear_rejections()
        self.mission_status = ACCEPTED
        # The robot is at the first node: it counts as traversed, so it is not left in nodeStates.
        self._traverse(self.node_states.pop(0))
        return True

    def _apply_update(self, order: dict) -> bool:
        """Stitch an order update at the decision point (2.1 section 6.6.2 steps 7-8, 3.0 section 6.1.2 steps 9-10)."""
        nodes = sorted(order["nodes"], key=lambda node: node["sequenceId"])
        node_id, sequence_id, _ = self._decision_point()
        if (nodes[0]["nodeId"], nodes[0]["sequenceId"]) != (node_id, sequence_id):
            self._reject(
                order["orderId"],
                f"update starts at {nodes[0]['nodeId']} (sequenceId {nodes[0]['sequenceId']}), "
                f"not at the decision point {node_id} (sequenceId {sequence_id})",
                "nodes[0]",
                kind=Reject.STITCH,
            )
            return False

        # Everything after the decision point is horizon: the update's base and horizon replace it.
        # The stitch node's actions are not run again.
        edges = [edge for edge in order.get("edges", []) if edge["sequenceId"] > sequence_id]
        problem = self._reused_action_id(sequence_id, nodes[1:]) or self._size_after_update(
            sequence_id, nodes[1:], edges
        )
        if problem:
            self._reject(order["orderId"], *problem)
            return False
        self._drop_after(sequence_id)
        self._add_to_order(nodes[1:], sorted(edges, key=lambda edge: edge["sequenceId"]))

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
        return True

    def _size_after_update(self, sequence_id: int, nodes: list[dict], edges: list[dict]) -> Problem | None:
        """Problem if what stays up to the decision point plus the update's nodes and edges outgrows the limits."""
        kept_nodes = sum(1 for node in self.node_states if node["sequenceId"] <= sequence_id)
        kept_edges = sum(1 for edge in self.edge_states if edge["sequenceId"] <= sequence_id)
        kept_actions = len(self.action_states) - len(self._horizon_action_ids(sequence_id))
        pair = check_size(
            kept_nodes + len(nodes), kept_edges + len(edges), kept_actions + count_actions(nodes) + count_actions(edges)
        )
        return Problem(*pair) if pair else None

    def _horizon_action_ids(self, sequence_id: int) -> set[str]:
        """The actions of the nodes after `sequence_id`: what an update replaces (edge actions are rejected, see
        validation._check_action_types, so orders carry node actions only)."""
        return {action_id for s, ids in self._node_actions.items() if s > sequence_id for action_id in ids}

    def _reused_action_id(self, sequence_id: int, nodes: list[dict]) -> Problem | None:
        """An update may not give an action the id of one the order keeps (it would run twice, at the first node
        that names it). The replaced horizon's ids may come again."""
        kept = {action["actionId"] for action in self.action_states} - self._horizon_action_ids(sequence_id)
        for i, node in enumerate(nodes):
            for j, action in enumerate(node.get("actions", [])):
                if action["actionId"] in kept:
                    return Problem(
                        f"actionId {action['actionId']!r} is already used by the order",
                        f"nodes[{i + 1}].actions[{j}].actionId",
                        Reject.STITCH,
                    )
        return None

    def _drop_after(self, sequence_id: int) -> None:
        """Forget the nodes, edges and actions after `sequence_id` (the horizon an update replaces)."""
        for sequence in [s for s in self._node_actions if s > sequence_id]:
            self._forget_actions(self._node_actions.pop(sequence))
        self.node_states = [node for node in self.node_states if node["sequenceId"] <= sequence_id]
        self.edge_states = [edge for edge in self.edge_states if edge["sequenceId"] <= sequence_id]

    def _add_to_order(self, nodes: list[dict], edges: list[dict]) -> None:
        """Add nodes, edges and their actions (in WAITING) to the remaining order."""
        for node in nodes:
            self.node_states.append(
                {
                    "nodeId": node["nodeId"],
                    "sequenceId": node["sequenceId"],
                    "released": node["released"],
                    "nodePosition": {
                        "x": node["nodePosition"]["x"],
                        "y": node["nodePosition"]["y"],
                        "mapId": node["nodePosition"].get("mapId", MAP_ID),
                    },
                }
            )
            if node.get("actions"):  # no empty entries: the maps hold only what is still to run
                self._node_actions[node["sequenceId"]] = self._add_actions(node["actions"])
        for edge in edges:
            self.edge_states.append(
                {"edgeId": edge["edgeId"], "sequenceId": edge["sequenceId"], "released": edge["released"]}
            )

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
                # hypot, not squares: tiny axes or far points must not overflow
                return math.hypot(u / a, v / b) <= 1
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
