"""Broker logins and per-robot permissions (D-23) on the real stack."""

import json
import threading
import time

from conftest import HOST, LOCAL_HOST, LOGIN, MQTT_PORT, SHARED, UI_PORT, VDA, wait_for
from websockets.exceptions import InvalidStatus


def connect(stack, username, password):
    """Connect and return (client, result of the login)."""
    done, result = threading.Event(), {}
    client = stack.mqtt_client(username, password)
    client.on_connect = lambda c, u, f, reason_code, p: (result.update(rc=str(reason_code)), done.set())
    client.connect(HOST, stack.mqtt_port, 10)
    client.loop_start()
    done.wait(10)
    return client, result.get("rc")


def test_anonymous_and_wrong_password_logins_are_refused(stack):
    robot_password = stack.secret("simulator/password")
    attempts = [
        (None, None),
        ("tools", "wrong"),
        ("ActuNode.robot_01", stack.tools_password),
        ("robot_01", robot_password),  # the old serial-only login name no longer exists (D-28)
    ]
    for username, password in attempts:
        client, rc = connect(stack, username, password)
        client.loop_stop()
        assert rc == "Not authorized", (username, rc)


def test_a_robot_can_publish_only_as_itself(stack):
    """robot_01's login cannot publish robot_02's state, order robot_02, inject failures, or publish its
    own serial under another manufacturer (D-28)."""
    robot_password = stack.secret("simulator/password")
    client, rc = connect(stack, "ActuNode.robot_01", robot_password)
    assert rc == "Success"

    attempts = {
        f"uagv/v{VDA}/ActuNode/robot_02/state": "as-robot_02",
        f"uagv/v{VDA}/ActuNode/robot_02/order": "orders-robot_02",
        "actunode/v1/sim/robot_02/inject": "injects-robot_02",
        f"uagv/v{VDA}/OtherVendor/robot_01/state": "as-other-manufacturer",
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


def test_other_web_pages_cannot_use_the_api_through_nginx(stack):
    """D-24 on the real stack (browser -> nginx -> backend): DNS rebinding and cross-site requests."""
    import asyncio

    import httpx
    import websockets

    base = f"{stack.http_base}/api"
    verify = stack.ssl_context or True
    assert httpx.get(f"{base}/robots", headers={"Host": "attacker.example"}, verify=verify).status_code == 400
    cross_site = httpx.post(f"{base}/recording/start", headers={"Origin": "https://attacker.example"}, verify=verify)
    assert cross_site.status_code == 403
    assert stack.api.get("/recording").json()["recording"] is None

    async def open_feed(origin):
        url = f"{stack.ws_base}/api/ws"
        ssl_options = {"ssl": stack.ssl_context} if stack.ssl_context else {}
        async with websockets.connect(
            url, origin=origin, additional_headers=stack.session_cookie(), **ssl_options
        ) as ws:
            return (await asyncio.wait_for(ws.recv(), 5))[:20]

    assert asyncio.run(open_feed(stack.http_base)).startswith('{"type"')
    try:
        asyncio.run(open_feed("https://attacker.example"))
        raise AssertionError("cross-site WebSocket was accepted")
    except InvalidStatus as refused:
        assert refused.response.status_code == 403


def test_with_login_required_nothing_works_without_a_session(stack):
    """D-25: sharing mode. Skipped when the stack runs without login (local mode)."""
    import asyncio

    import httpx
    import pytest
    import websockets

    if not LOGIN:
        pytest.skip("stack runs without login")
    base = f"{stack.http_base}/api"
    verify = stack.ssl_context or True
    assert httpx.get(f"{base}/robots", verify=verify).status_code == 401
    assert httpx.post(f"{base}/login", json={"token": "wrong"}, verify=verify).status_code == 401
    assert httpx.get(f"{base}/health", verify=verify).status_code == 200

    async def open_feed():
        ssl_options = {"ssl": stack.ssl_context} if stack.ssl_context else {}
        async with websockets.connect(f"{stack.ws_base}/api/ws", **ssl_options) as ws:
            await ws.recv()

    with pytest.raises(InvalidStatus):
        asyncio.run(open_feed())


def test_shared_mode_offers_only_encrypted_ports_to_the_network(stack):
    """D-26: plain HTTP and MQTT are published on 127.0.0.1 only. Checkable only when the tests reach
    the stack over the network (ACTUNODE_E2E_HOST is not this machine's loopback)."""
    import socket

    import pytest

    if LOCAL_HOST:
        pytest.skip("tests run on loopback; nothing to check from the network side")
    for port in (UI_PORT, MQTT_PORT):
        with pytest.raises(OSError):
            socket.create_connection((HOST, port), timeout=3).close()


def test_tls_endpoints_reject_clients_that_do_not_trust_the_ca(stack):
    """The certificate is really in use and checked: a client trusting only the system CAs fails."""
    import socket
    import ssl

    import pytest

    if not SHARED:
        pytest.skip("stack runs without TLS endpoints")
    from conftest import MQTTS_PORT, UI_TLS_PORT

    system_only = ssl.create_default_context()
    for port in (UI_TLS_PORT, MQTTS_PORT):
        with socket.create_connection((HOST, port), timeout=5) as raw, pytest.raises(ssl.SSLCertVerificationError):
            system_only.wrap_socket(raw, server_hostname=HOST)
