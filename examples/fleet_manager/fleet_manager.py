"""A minimal fleet manager (master control), to show how one is tested with ActuNode (D-48).

It talks only VDA 5050 over MQTT, like a real one: it logs in with its own master control login (D-47),
shuttles one robot between two locations, and reacts when the robot reports `pathBlocked`. How it reacts
is a choice, so the same scenario can show a fleet manager that passes and one that fails:

    cancel     cancelOrder; the next job goes out as usual
    reroute    cancelOrder, then the same job again around the blocked aisle (a detour waypoint)
    escalate   startPause and an alert for an operator (here: the log); stopPause once the aisle is clear
    ignore     nothing: the robot stays blocked (a fleet manager with a bug)

    docker compose run --rm mqtt-init add-master example        # once; prints the password
    docker compose up -d --force-recreate mqtt-init mosquitto
    python examples/fleet_manager/fleet_manager.py --password-file pw.txt --policy cancel

A dense map and habits of real fleet managers, each a good and a bad option (scenarios in this folder tell them apart):

    --spacing 2              a node every 2 m along each leg (default: only start, detour and destination)
    --base 4                 release only 4 nodes at a time (the rest is horizon); needs --spacing to matter
    --extend early|late      extend the base while the robot is still driving (early), or only once it has
                             stopped at the end of it (late: a fast robot waits there)
    --progress any|strict    strict treats a state that reports several nodes passed at once as a lost position

Only paho-mqtt is needed (pip install paho-mqtt). Not a product: no safety logic, one robot, straight lines.
"""

import argparse
import json
import logging
import math
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("example-fleet-manager")

# The demo warehouse (backend/app/warehouse.py), in metres: this fleet manager's own map.
LOCATIONS = {
    "RECEIVING_DOOR_1": (2.0, 18.0),
    "RECEIVING_DOOR_2": (2.0, 14.0),
    "STORAGE_A17": (14.0, 18.0),
    "STORAGE_B04": (18.0, 12.0),
    "PACK_SORT": (28.0, 15.0),
    "CONVEYOR": (24.0, 4.0),
    "LOADING_DOCK_1": (38.0, 18.0),
    "LOADING_DOCK_2": (38.0, 12.0),
}
POLICIES = ("cancel", "reroute", "escalate", "ignore")


def interpolate(stops: list[tuple[str, float, float]], spacing: float) -> list[tuple[str, float, float]]:
    """Intermediate nodes every `spacing` metres (at most) along each straight leg; spacing 0 adds none."""
    if not spacing:
        return list(stops)
    out = [stops[0]]
    for (_, ax, ay), (name, bx, by) in zip(stops, stops[1:], strict=False):
        parts = max(1, math.ceil(math.hypot(bx - ax, by - ay) / spacing))
        for k in range(1, parts):
            out.append((f"wp{len(out)}", ax + (bx - ax) * k / parts, ay + (by - ay) * k / parts))
        out.append((name, bx, by))
    return out


def build(stops, map_id: str, released: int, first: int = 0) -> tuple[list[dict], list[dict]]:
    """Nodes (sequenceId 2*i) and edges (2*i+1) from node `first` on; the first `released` nodes of the whole
    order are released, the rest is horizon (edges follow the node they lead to)."""
    nodes = [
        {
            "nodeId": name,
            "sequenceId": 2 * i,
            "released": i < released,
            "actions": [],
            "nodePosition": {"x": px, "y": py, "mapId": map_id},
        }
        for i, (name, px, py) in enumerate(stops)
    ][first:]
    edges = [
        {
            "edgeId": f"{a['nodeId']}->{b['nodeId']}",
            "sequenceId": a["sequenceId"] + 1,
            "released": b["sequenceId"] // 2 < released,
            "startNodeId": a["nodeId"],
            "endNodeId": b["nodeId"],
            "actions": [],
        }
        for a, b in zip(nodes, nodes[1:], strict=False)
    ]
    return nodes, edges


def extension_due(mode: str, base: int, released: int, total: int, state: dict) -> bool:
    """Is it time to release more of the order? early: few released nodes left ahead of the robot; late: it
    has stopped at the last released node."""
    last = state.get("lastNodeSequenceId")
    if not base or released >= total or isinstance(last, bool) or not isinstance(last, int):
        return False
    if mode == "late":
        return not state.get("driving") and last == 2 * (released - 1)
    ahead = sum(1 for i in range(released) if 2 * i > last)
    return ahead <= max(1, base // 2)


def skipped(previous: int | None, last) -> bool:
    """Strict progress: more than 2 sequence ids at once is more than one node passed between two states."""
    return previous is not None and isinstance(last, int) and not isinstance(last, bool) and last - previous > 2


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class FleetManager:
    def __init__(
        self,
        client,
        vda: str,
        manufacturer: str,
        robot: str,
        route: list[str],
        policy: str,
        spacing: float = 0,
        base: int = 0,
        extend: str = "early",
        progress: str = "any",
    ):
        self.client = client
        self.version = "2.1.0" if vda == "2" else "3.0.0"
        self.manufacturer, self.robot = manufacturer, robot
        self.prefix = f"uagv/v{vda}/{manufacturer}/{robot}"
        self.route, self.policy = route, policy
        self.spacing, self.base, self.extend, self.progress = spacing, base, extend, progress
        self.stops: list[tuple[str, float, float]] = []
        self.map_id = "warehouse"
        self.released = 0  # nodes of the current order released so far
        self.update_id = 0
        self.last_seq: tuple[str, int] | None = None  # (order, lastNodeSequenceId) of the previous state
        self.cancelled_orders: set[str] = set()
        self.logged_errors: set[tuple] = set()
        self.next_stop = 0
        self.header_ids: dict[str, int] = {}
        self.jobs = 0
        # Order ids must never repeat, also across restarts: a robot takes a known orderId as an update of that
        # order (and refuses updates to a cancelled one).
        self.run = format(int(time.time() * 1000) % 0xFFFFFFFF, "08x")
        self.paused_by_us = False
        self.order_id: str | None = None
        self.destination: str | None = None
        self.block_handled = False  # the current block episode was reacted to; ends when the block clears
        self.warned_no_position = False
        self.reroute_pending = False
        self.state: dict | None = None
        self.sent_at: float | None = None  # an order sent and not yet confirmed in the robot's state
        self.clock = time.monotonic
        self.update_pending: tuple[float, int] | None = None  # (sent at, released nodes the robot showed then)

    # --- sending ---------------------------------------------------------------------

    def _send(self, topic: str, body: dict) -> None:
        self.header_ids[topic] = self.header_ids.get(topic, 0) + 1
        message = {
            "headerId": self.header_ids[topic],
            "timestamp": now(),
            "version": self.version,
            "manufacturer": self.manufacturer,
            "serialNumber": self.robot,
            **body,
        }
        self.client.publish(f"{self.prefix}/{topic}", json.dumps(message), qos=1)

    def position(self) -> tuple[float, float, str] | None:
        """Where the robot says it is (2.1: agvPosition, 3.0: mobileRobotPosition); None before it says."""
        position = (self.state or {}).get("agvPosition") or (self.state or {}).get("mobileRobotPosition") or {}
        x, y = position.get("x"), position.get("y")
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in (x, y)):
            return None
        return x, y, position.get("mapId", "warehouse")

    def send_order(self, destination: str, detour: bool = False) -> None:
        x, y, map_id = self.position()
        self.jobs += 1
        self.order_id = f"example-{self.robot}-{self.run}-{self.jobs}"
        self.destination = destination
        stops = [("start", x, y)]
        if detour:  # around the blocked aisle: a waypoint 3 m to the side of the straight line
            tx, ty = LOCATIONS[destination]
            stops.append(("detour", (x + tx) / 2, min(19.0, (y + ty) / 2 + 3)))
        stops.append((destination, *LOCATIONS[destination]))
        self.stops, self.map_id, self.update_id = interpolate(stops, self.spacing), map_id, 0
        self.released = min(self.base, len(self.stops)) if self.base else len(self.stops)
        nodes, edges = build(self.stops, map_id, self.released)
        self._send("order", {"orderId": self.order_id, "orderUpdateId": 0, "nodes": nodes, "edges": edges})
        self.sent_at = self.clock()
        self.update_pending = None
        log.info("order %s: %s to %s%s", self.order_id, self.robot, destination, " via a detour" if detour else "")

    @staticmethod
    def reported_released(state: dict) -> int | None:
        """How many nodes of the order the robot's state shows as released: up to its last released node, or up to
        the node it is at when none is left ahead; None when it shows neither."""
        ahead = [
            n["sequenceId"]
            for n in state.get("nodeStates") or []
            if n.get("released") is True and isinstance(n.get("sequenceId"), int)
        ]
        last = state.get("lastNodeSequenceId")
        if not ahead and (isinstance(last, bool) or not isinstance(last, int)):
            return None
        return (max(ahead) if ahead else last) // 2 + 1

    def extend_base(self, released: int) -> None:
        """An order update: the stitching node (the robot's last released one), the next `base` nodes released, the
        horizon. It is based on what the robot reports, so a lost or rejected update is simply sent again."""
        stitch = released - 1
        self.released = min(len(self.stops), released + self.base)
        self.update_id += 1
        nodes, edges = build(self.stops, self.map_id, self.released, first=stitch)
        self._send("order", {"orderId": self.order_id, "orderUpdateId": self.update_id, "nodes": nodes, "edges": edges})
        self.update_pending = (self.clock(), released)
        log.info("order %s: base extended to %d of %d nodes", self.order_id, self.released, len(self.stops))

    def instant(self, action_type: str) -> None:
        action = {
            "actionId": f"{action_type}-{self.run}-{self.jobs}",
            "actionType": action_type,
            "blockingType": "NONE",
        }
        self._send("instantActions", {"actions": [action]})
        log.info("%s sent to %s", action_type, self.robot)

    # --- reacting to the robot -----------------------------------------------------------

    def on_state(self, state: dict) -> None:
        self.state = state
        self.watch(state)
        blocked = any(e.get("errorType") == "pathBlocked" for e in state.get("errors") or [])
        if not blocked:
            self.block_handled = False
        idle = not state.get("nodeStates") and not state.get("edgeStates") and not state.get("driving")
        if self.paused_by_us and not blocked:
            # The operator cleared the aisle: let the robot go on with its order.
            self.paused_by_us = False
            self.instant("stopPause")
            log.info("%s: aisle clear, resuming", self.robot)
        elif blocked and not self.block_handled:
            self.block_handled = True
            self.react_to_block(state.get("orderId"))
        elif self.sent_at is not None and state.get("orderId") != self.order_id:
            # Not taken yet: a state from before the order arrived still looks idle. Do not send it twice.
            if self.clock() - self.sent_at > 5:
                errors = [e.get("errorDescription") for e in state.get("errors") or []]
                log.error("order %s was not taken by %s: %s", self.order_id, self.robot, errors or "no answer")
                self.sent_at = None
        elif idle and not state.get("paused"):
            if self.position() is None:  # an order needs a start position: wait until the robot reports one
                if not self.warned_no_position:
                    self.warned_no_position = True
                    log.warning("%s reports no position yet; no order sent", self.robot)
                return
            self.sent_at = None
            if self.reroute_pending:
                self.reroute_pending = False
                self.send_order(self.destination, detour=True)
            else:
                destination = self.route[self.next_stop % len(self.route)]
                self.next_stop += 1
                self.send_order(destination)

    def watch(self, state: dict) -> None:
        """Rejections of our order updates, several nodes at once (strict), extending the base."""
        for error in state.get("errors") or []:
            kind, text = error.get("errorType"), error.get("errorDescription")
            if kind != "pathBlocked" and (kind, text) not in self.logged_errors:
                self.logged_errors.add((kind, text))
                log.error("%s reports error %s: %s", self.robot, kind, text)
        order, last = state.get("orderId"), state.get("lastNodeSequenceId")
        if self.progress == "strict" and order:
            previous = self.last_seq[1] if self.last_seq and self.last_seq[0] == order else None
            if skipped(previous, last) and order not in self.cancelled_orders:
                self.cancelled_orders.add(order)
                log.error(
                    "%s reported several nodes at once (sequence %s -> %s); position treated as unknown",
                    self.robot,
                    previous,
                    last,
                )
                self.instant("cancelOrder")
        self.last_seq = (order, last) if isinstance(last, int) else None
        active = order == self.order_id and state.get("nodeStates")
        blocked = any(e.get("errorType") == "pathBlocked" for e in state.get("errors") or [])
        if active and not blocked and order not in self.cancelled_orders:
            released = self.reported_released(state)
            if released is None:
                return
            if self.update_pending and released > self.update_pending[1]:
                self.update_pending = None  # the robot shows the longer base
            elif self.update_pending and self.clock() - self.update_pending[0] >= 3:
                log.warning("%s still shows the old base %d s after an update; sending it again", self.robot, 3)
                self.update_pending = None
            if not self.update_pending and extension_due(self.extend, self.base, released, len(self.stops), state):
                self.extend_base(released)

    def react_to_block(self, order_id: str | None) -> None:
        log.warning("%s reports pathBlocked on order %s (policy: %s)", self.robot, order_id, self.policy)
        if order_id != self.order_id:
            # An order from before this fleet manager started (or someone else's): it knows no job to retry.
            log.warning("order %s is not one of ours; reacting to it all the same", order_id)
        if self.policy == "cancel":
            self.instant("cancelOrder")
        elif self.policy == "reroute":
            self.reroute_pending = self.destination is not None and order_id == self.order_id
            self.instant("cancelOrder")
        elif self.policy == "escalate":
            self.instant("startPause")
            self.paused_by_us = True
            log.error(
                "ESCALATION: %s is blocked on its way to %s; an operator must clear the aisle",
                self.robot,
                self.destination,
            )
        # ignore: nothing at all


def main() -> None:
    import paho.mqtt.client as mqtt  # only needed to run it, not to test it

    parser = argparse.ArgumentParser(description="A minimal VDA 5050 fleet manager for testing with ActuNode.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--ca-file", type=Path, help="CA to trust for MQTT over TLS (port 8883)")
    parser.add_argument("--user", default="master@example")
    parser.add_argument("--password-file", type=Path, required=True, help="the master control login's password")
    parser.add_argument("--vda", choices=("2", "3"), default="2")
    parser.add_argument("--manufacturer", default="ActuNode")
    parser.add_argument("--robot", default="robot_03")
    parser.add_argument("--route", nargs="+", default=["RECEIVING_DOOR_1", "LOADING_DOCK_1"], choices=list(LOCATIONS))
    parser.add_argument("--policy", choices=POLICIES, default="cancel")
    parser.add_argument("--spacing", type=float, default=0, help="a node every this many metres (0 = off, else >= 0.5)")
    parser.add_argument(
        "--base", type=int, default=0, help="release only this many nodes at a time (0 = all, else >= 2)"
    )
    parser.add_argument(
        "--extend", choices=("early", "late"), default="early",
        help="when to release more (needs --base; without it this has no effect)",
    )  # fmt: skip
    parser.add_argument(
        "--progress", choices=("any", "strict"), default="any",
        help="strict: cancel the order when a state reports several nodes passed at once",
    )  # fmt: skip
    parser.add_argument("--max-seconds", type=float, help="stop after this long (default: until Ctrl-C)")
    args = parser.parse_args()
    if args.spacing and args.spacing < 0.5:
        parser.error("--spacing must be 0 (off) or at least 0.5")
    if args.base and args.base < 2:
        parser.error("--base must be 0 (whole order) or at least 2")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=f"{args.user}-example")
    client.username_pw_set(args.user, args.password_file.read_text().strip())
    if args.ca_file:
        client.tls_set(ca_certs=str(args.ca_file), tls_version=ssl.PROTOCOL_TLS_CLIENT)
    manager = FleetManager(
        client,
        args.vda,
        args.manufacturer,
        args.robot,
        args.route,
        args.policy,
        args.spacing,
        args.base,
        args.extend,
        args.progress,
    )

    def on_message(_client, _userdata, message):
        try:
            state = json.loads(message.payload)
        except ValueError:
            return  # a fleet manager must survive a malformed message
        if isinstance(state, dict):
            try:
                manager.on_state(state)
            except Exception:  # paho would stop its network thread silently; a fleet manager must keep going
                log.exception("could not handle a state message")

    def on_connect(_client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            log.error("login refused: %s", reason)
            return
        client.subscribe(f"{manager.prefix}/state", qos=0)
        log.info("connected as %s; driving %s (policy: %s)", args.user, manager.prefix, args.policy)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port)
    client.loop_start()
    started = time.monotonic()
    try:
        while args.max_seconds is None or time.monotonic() - started < args.max_seconds:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
