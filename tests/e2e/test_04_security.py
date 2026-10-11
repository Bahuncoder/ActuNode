"""Broker logins and per-robot permissions (D-23) on the real stack."""

import json
import threading
import time

from conftest import HOST, MQTT_PORT, VDA, wait_for


def connect(stack, username, password):
    """Connect and return (client, result of the login)."""
    done, result = threading.Event(), {}
    client = stack.mqtt_client(username, password)
    client.on_connect = lambda c, u, f, reason_code, p: (result.update(rc=str(reason_code)), done.set())
    client.connect(HOST, MQTT_PORT, 10)
    client.loop_start()
    done.wait(10)
    return client, result.get("rc")


def test_anonymous_and_wrong_password_logins_are_refused(stack):
    for username, password in [(None, None), ("tools", "wrong"), ("robot_01", stack.tools_password)]:
        client, rc = connect(stack, username, password)
        client.loop_stop()
        assert rc == "Not authorized", (username, rc)


def test_a_robot_can_publish_only_as_itself(stack):
    """robot_01's login cannot publish robot_02's state, order robot_02, or inject failures."""
    robot_password = stack.secret("simulator/password")
    client, rc = connect(stack, "robot_01", robot_password)
    assert rc == "Success"

    attempts = {
        f"uagv/v{VDA}/ActuNode/robot_02/state": "as-robot_02",
        f"uagv/v{VDA}/ActuNode/robot_02/order": "orders-robot_02",
        "actunode/v1/sim/robot_02/inject": "injects-robot_02",
    }
    for topic, tag in attempts.items():
        client.publish(topic, json.dumps({"serialNumber": "robot_01", "SPOOF": tag}), qos=1).wait_for_publish(5)
    client.publish(f"uagv/v{VDA}/ActuNode/robot_01/state", json.dumps({"SPOOF": "own"}), qos=1).wait_for_publish(5)
    client.loop_stop()

    def spoof_tags():
        messages = stack.api.get("/messages").json()
        return {
            m["payload"].get("SPOOF") for m in messages if isinstance(m["payload"], dict) and m["payload"].get("SPOOF")
        }

    wait_for(lambda: "own" in spoof_tags(), 10, "robot_01's own message to arrive")
    time.sleep(1)  # give any wrongly allowed message the same chance to arrive
    assert spoof_tags() == {"own"}


def test_tools_login_reads_but_cannot_publish(stack):
    client, rc = connect(stack, "tools", stack.tools_password)
    assert rc == "Success"
    client.publish(f"uagv/v{VDA}/ActuNode/robot_03/state", json.dumps({"SPOOF": "tools"}), qos=1).wait_for_publish(5)
    client.loop_stop()
    time.sleep(1.5)

    messages = stack.api.get("/messages").json()
    assert not any(isinstance(m["payload"], dict) and m["payload"].get("SPOOF") == "tools" for m in messages)
