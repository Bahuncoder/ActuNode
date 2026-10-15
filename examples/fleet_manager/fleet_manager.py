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

Only paho-mqtt is needed (pip install paho-mqtt). Not a product: no safety logic, one robot, straight lines.
"""

import argparse
import json
import logging
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


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class FleetManager:
    def __init__(self, client, vda: str, manufacturer: str, robot: str, route: list[str], policy: str):
        self.client = client
        self.version = "2.1.0" if vda == "2" else "3.0.0"
        self.manufacturer, self.robot = manufacturer, robot
        self.prefix = f"uagv/v{vda}/{manufacturer}/{robot}"
        self.route, self.policy = route, policy
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
        nodes = [
            {
                "nodeId": name,
                "sequenceId": 2 * i,
                "released": True,
                "actions": [],
                "nodePosition": {"x": px, "y": py, "mapId": map_id},
            }
            for i, (name, px, py) in enumerate(stops)
        ]
        edges = [
            {
                "edgeId": f"{a['nodeId']}->{b['nodeId']}",
                "sequenceId": 2 * i + 1,
                "released": True,
                "startNodeId": a["nodeId"],
                "endNodeId": b["nodeId"],
                "actions": [],
            }
            for i, (a, b) in enumerate(zip(nodes, nodes[1:], strict=False))
        ]
        self._send("order", {"orderId": self.order_id, "orderUpdateId": 0, "nodes": nodes, "edges": edges})
        self.sent_at = time.monotonic()
        log.info("order %s: %s to %s%s", self.order_id, self.robot, destination, " via a detour" if detour else "")

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
            if time.monotonic() - self.sent_at > 5:
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
    parser.add_argument("--max-seconds", type=float, help="stop after this long (default: until Ctrl-C)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=f"{args.user}-example")
    client.username_pw_set(args.user, args.password_file.read_text().strip())
    if args.ca_file:
        client.tls_set(ca_certs=str(args.ca_file), tls_version=ssl.PROTOCOL_TLS_CLIENT)
    manager = FleetManager(client, args.vda, args.manufacturer, args.robot, args.route, args.policy)

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
