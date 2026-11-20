"""Conformance checks a scenario cannot express (D-52): orders ActuNode's mission sender would never build.

Sends them with a master control login (D-47) straight to the robot and reports what the robot says.

    docker compose run --rm mqtt-init add-master conformance <manufacturer>   # once; then reload the broker
    python conformance/raw_checks.py --password-file pw.txt [--manufacturer ROS2 --serial nav2_01]

Checks (VDA 5050 2.1):
  unreachable  a node inside an obstacle: the robot cannot get there. It must not report the node reached
               (lastNodeId is the last node *reached*, section 6.10.6), and should report an error.
  unknown-map  a node on a map the robot does not have: 2.1 section 6.7.1 requires checking the map before
               accepting (2.0 robots: informational).
  invalid      a node whose nodePosition lacks x: the robot must reject the order with an error (section 6.1.1),
               not drop it silently.
  single-node  one released node at the robot's position, no edges: "one node is enough for a valid order".
  empty-order  an order without nodes (an MC habit: an empty order as a cancel; VDA 5050 cancels with the cancelOrder
               instant action) is rejected with an error and the vehicle keeps reporting.
  horizon      a robot stops at the last released node (the end of the base) and continues when an order update
               extends the base (section 6.6.1).
  error-clears an error from a rejected order must not outlive the next valid order, which the robot must accept.
Needs paho-mqtt and a lab at localhost (plain MQTT on 1883; the login must be allowed there).
"""

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

INSIDE_A_RACK = (15.0, 11.0)  # backend/app/warehouse.py: racks along x 10-20 around y 11


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Robot:
    def __init__(self, args):
        self.prefix = f"uagv/v2/{args.manufacturer}/{args.serial}"
        self.version, self.manufacturer, self.serial = args.version, args.manufacturer, args.serial
        self.state: dict = {}
        self.header = 0
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="conformance-checks")
        self.client.username_pw_set(f"master@{args.master}", args.password_file.read().strip())
        self.received = 0  # state messages so far
        self.client.on_message = self.on_message
        self.client.connect(args.host, args.port)
        self.client.loop_start()
        self.client.subscribe(f"{self.prefix}/state")
        deadline = time.monotonic() + 40
        while "agvPosition" not in self.state and time.monotonic() < deadline:
            time.sleep(0.2)
        if "agvPosition" not in self.state:
            sys.exit(f"no state from {self.prefix} in 40 s")

    def on_message(self, client, userdata, message) -> None:
        self.state.update(json.loads(message.payload or b"{}"))
        self.received += 1

    def send(self, order_id: str, update_id: int, nodes: list[dict], edges: list[dict]) -> None:
        self.header += 1
        message = {
            "headerId": self.header, "timestamp": now(), "version": self.version,
            "manufacturer": self.manufacturer, "serialNumber": self.serial,
            "orderId": order_id, "orderUpdateId": update_id, "nodes": nodes, "edges": edges,
        }  # fmt: skip
        self.client.publish(f"{self.prefix}/order", json.dumps(message), qos=1)

    def wait_until(self, condition, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.2)
        return condition()

    def order(self, order_id: str, x: float, y: float, map_id: str, drop: str | None = None) -> None:
        here = self.state["agvPosition"]
        start = {"x": here["x"], "y": here["y"], "theta": here.get("theta", 0.0), "mapId": here["mapId"]}
        self.header += 1
        node = {"released": True, "actions": []}
        message = {
            "headerId": self.header, "timestamp": now(), "version": self.version,
            "manufacturer": self.manufacturer, "serialNumber": self.serial,
            "orderId": order_id, "orderUpdateId": 0,
            "nodes": [
                {**node, "nodeId": "here", "sequenceId": 0,
                 "nodePosition": start},
                {**node, "nodeId": "target", "sequenceId": 2,
                 "nodePosition": {"x": x, "y": y, "theta": 0.0, "mapId": map_id}},
            ],
            "edges": [{"edgeId": "here-target", "sequenceId": 1, "released": True, "startNodeId": "here",
                       "endNodeId": "target", "actions": []}],
        }  # fmt: skip
        if drop:  # make the order invalid: remove a mandatory field from the target's nodePosition
            del message["nodes"][1]["nodePosition"][drop]
        self.client.publish(f"{self.prefix}/order", json.dumps(message), qos=1)

    def cancel(self, seconds: float) -> None:
        """cancelOrder, then wait until the order is gone: a robot refuses a new order while one is still open."""
        self.header += 1
        action = {"actionId": f"conformance-cancel-{self.header}", "actionType": "cancelOrder", "blockingType": "HARD",
                  "actionParameters": []}  # fmt: skip
        message = {
            "headerId": self.header, "timestamp": now(), "version": self.version,
            "manufacturer": self.manufacturer, "serialNumber": self.serial, "actions": [action],
        }  # fmt: skip
        self.client.publish(f"{self.prefix}/instantActions", json.dumps(message), qos=1)
        # Wait for the robot to report the cancel done (FINISHED, or FAILED when nothing was open): until then it may
        # still cancel the next order, e.g. while Nav2 is retrying a goal it cannot reach.
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            done = [a for a in self.state.get("actionStates") or [] if a.get("actionId") == action["actionId"]]
            if done and done[0].get("actionStatus") in ("FINISHED", "FAILED"):
                break
            time.sleep(0.2)
        time.sleep(1)

    def watch(self, seconds: float) -> dict:
        time.sleep(seconds)
        return dict(self.state)


def node(node_id: str, sequence: int, x: float, y: float, map_id: str, released: bool = True) -> dict:
    return {"nodeId": node_id, "sequenceId": sequence, "released": released, "actions": [],
            "nodePosition": {"x": x, "y": y, "theta": 0.0, "mapId": map_id}}  # fmt: skip


def edge(start: str, end: str, sequence: int, released: bool = True) -> dict:
    return {"edgeId": f"{start}-{end}", "sequenceId": sequence, "released": released, "startNodeId": start,
            "endNodeId": end, "actions": []}  # fmt: skip


def new_errors(state: dict, before: list[str]) -> list[dict]:
    return [e for e in state.get("errors") or [] if json.dumps(e, sort_keys=True) not in before]


def error_types(state: dict, before: list[str]) -> list:
    return [e.get("errorType") for e in new_errors(state, before)]


def report(name: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--master", default="conformance")
    parser.add_argument("--password-file", type=argparse.FileType(), required=True)
    parser.add_argument("--manufacturer", default="ROS2")
    parser.add_argument("--serial", default="nav2_01")
    parser.add_argument("--version", default="2.0.0")
    parser.add_argument("--wait", type=float, default=45, help="seconds to give the robot per check")
    args = parser.parse_args()
    robot = Robot(args)
    results = []

    # Start clean (an order left open by an earlier run would make the robot refuse ours); count only new errors.
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    start = robot.state["agvPosition"]
    robot.order("conformance-unreachable", *INSIDE_A_RACK, start["mapId"])
    seen = robot.watch(args.wait)
    position = seen["agvPosition"]
    moved = math.dist((start["x"], start["y"]), (position["x"], position["y"]))
    at_target = math.dist((position["x"], position["y"]), INSIDE_A_RACK) < 1.0
    claims = seen.get("orderId") == "conformance-unreachable" and seen.get("lastNodeId") == "target"
    errors = [e.get("errorType") for e in seen.get("errors") or [] if json.dumps(e, sort_keys=True) not in before]
    results.append(
        report(
            "unreachable node is not reported reached",
            not (claims and not at_target),
            f"lastNodeId={seen.get('lastNodeId')!r}, at target={at_target}, moved {moved:.1f} m, errors={errors}",
        )
    )
    results.append(report("unreachable node is reported as an error", bool(errors), f"errors={errors}"))

    # Close the first order as a fleet manager would; only errors raised by this order count.
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    robot.order("conformance-unknown-map", start["x"] + 1, start["y"], "no_such_map")
    seen = robot.watch(10)
    errors = [e.get("errorType") for e in seen.get("errors") or [] if json.dumps(e, sort_keys=True) not in before]
    taken = seen.get("orderId") == "conformance-unknown-map"
    results.append(
        report(
            "order on an unknown map is rejected (2.1 section 6.7.1; informational for 2.0)",
            not taken and bool(errors),
            f"orderId={seen.get('orderId')!r}, errors={errors}",
        )
    )

    # An order the robot cannot read (nodePosition without its mandatory x): rejected with an error, not ignored
    # (section 6.1.1: "communicate this within an error message and ... reject the order"; validationError, 6.6.4.1).
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    robot.order("conformance-undecodable", start["x"] + 1, start["y"], start["mapId"], drop="x")
    seen = robot.watch(10)
    errors = [e.get("errorType") for e in seen.get("errors") or [] if json.dumps(e, sort_keys=True) not in before]
    taken = seen.get("orderId") == "conformance-undecodable"
    results.append(
        report(
            "an invalid order is rejected with an error, not ignored",
            not taken and bool(errors),
            f"orderId={seen.get('orderId')!r}, errors={errors}",
        )
    )

    # An order of one node: "one node is enough for a valid order" (the order schema, section 6.6.1).
    run = int(time.time())
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    here = robot.state["agvPosition"]
    order_id = f"conformance-single-{run}"
    robot.send(order_id, 0, [node("only", 0, here["x"], here["y"], here["mapId"])], [])

    def single_done() -> bool:
        s = robot.state
        return (
            s.get("orderId") == order_id
            and s.get("lastNodeId") == "only"
            and not s.get("nodeStates")
            and not s.get("edgeStates")
        )

    done = robot.wait_until(single_done, args.wait)
    refs = [e for e in new_errors(robot.state, before) if order_id in json.dumps(e)]
    results.append(
        report(
            "a single-node order is accepted and finished",
            done and not refs,
            f"orderId={robot.state.get('orderId')!r}, lastNodeId={robot.state.get('lastNodeId')!r}, "
            f"nodeStates={len(robot.state.get('nodeStates') or [])}, errors={error_types(robot.state, before)}",
        )
    )

    # An empty order is not a cancel (VDA 5050 cancels with the cancelOrder instant action): reject it with an
    # error and stay up. Whether the running order continued is informational.
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    here = robot.state["agvPosition"]
    step = 4.0 if here["x"] + 4.0 < 9.5 else -4.0  # the open floor beside the racks (x 10-20)
    running = f"conformance-running-{run}"
    robot.send(running, 0, [node("a", 0, here["x"], here["y"], here["mapId"]),
                            node("b", 2, here["x"] + step, here["y"], here["mapId"])], [edge("a", "b", 1)])  # fmt: skip
    robot.wait_until(lambda: robot.state.get("orderId") == running, 10)
    robot.send(f"conformance-empty-{run}", 0, [], [])
    errored = robot.wait_until(lambda: bool(new_errors(robot.state, before)), 10)
    count = robot.received
    time.sleep(5)
    alive = robot.received > count
    continued = robot.state.get("orderId") == running
    results.append(
        report(
            "an empty order is rejected with an error, and the vehicle stays up",
            errored and alive,
            f"errors={error_types(robot.state, before)}, state messages in 5 s: {robot.received - count}, "
            f"the running order {'continued' if continued else 'was dropped'}",
        )
    )

    # The end of the base: the robot stops at the last released node, and goes on when the base is extended.
    robot.cancel(args.wait)
    here = robot.state["agvPosition"]
    step = 3.0 if here["x"] + 6.0 < 9.5 else -3.0
    m, order_id = here["mapId"], f"conformance-horizon-{run}"
    p1, p2 = (here["x"] + step, here["y"]), (here["x"] + 2 * step, here["y"])
    robot.send(order_id, 0, [node("n0", 0, here["x"], here["y"], m), node("n1", 2, *p1, m),
                             node("n2", 4, *p2, m, released=False)],
               [edge("n0", "n1", 1), edge("n1", "n2", 3, released=False)])  # fmt: skip

    def at(point) -> bool:
        s = robot.state["agvPosition"]
        return math.dist((s["x"], s["y"]), point) < 1.0

    reached = robot.wait_until(lambda: robot.state.get("lastNodeId") == "n1" and at(p1), args.wait)
    passed = False
    for _ in range(25):  # 5 s with the horizon unreleased
        time.sleep(0.2)
        passed = passed or robot.state.get("lastNodeId") == "n2" or not at(p1)
    stopped = reached and not passed and not robot.state.get("driving")
    robot.send(order_id, 1, [node("n1", 2, *p1, m), node("n2", 4, *p2, m)], [edge("n1", "n2", 3)])
    finished = robot.wait_until(
        lambda: robot.state.get("lastNodeId") == "n2" and at(p2) and not robot.state.get("nodeStates"), args.wait
    )
    results.append(
        report(
            "the vehicle stops at the end of the base and continues when it is extended",
            stopped and finished,
            f"reached n1={reached}, stayed at n1 for 5 s={stopped}, reached n2 after the update={finished}",
        )
    )

    # An error from a rejected order must not block (or outlive) the next valid order.
    robot.cancel(args.wait)
    before = [json.dumps(e, sort_keys=True) for e in robot.state.get("errors") or []]
    here = robot.state["agvPosition"]
    robot.order(f"conformance-rejected-{run}", here["x"] + 1, here["y"], here["mapId"], drop="x")
    errored = robot.wait_until(lambda: bool(new_errors(robot.state, before)), 10)
    rejection = [json.dumps(e, sort_keys=True) for e in new_errors(robot.state, before)]
    robot.cancel(args.wait)  # the next order may only start once the robot is idle
    order_id = f"conformance-after-{run}"
    robot.order(order_id, here["x"] + 1, here["y"], here["mapId"])
    finished = robot.wait_until(
        lambda: (
            robot.state.get("orderId") == order_id
            and robot.state.get("lastNodeId") == "target"
            and not robot.state.get("nodeStates")
        ),
        args.wait,
    )
    left = [e for e in robot.state.get("errors") or [] if json.dumps(e, sort_keys=True) in rejection]
    results.append(
        report(
            "a rejected order's error does not block the next order",
            errored and finished and not left,
            f"rejection reported={errored}, next order finished={finished}, "
            f"rejection error still in state={bool(left)}",
        )
    )
    robot.cancel(args.wait)
    robot.client.loop_stop()
    robot.client.disconnect()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
