"""Metrics on the real stack (A6, D-57): the backend's counters and the broker's own statistics ($SYS, which the
backend's login may read), scraped the way Prometheus would (a bearer token when login is required)."""

import re

import httpx
from conftest import LOGIN, wait_for


def scrape(stack) -> str:
    headers = {"Authorization": f"Bearer {stack.secret('backend/api-token')}"} if LOGIN else {}
    response = httpx.get(f"{stack.http_base}/api/metrics", headers=headers, verify=stack.ssl_context or True)
    assert response.status_code == 200, response.text
    return response.text


def sample(text: str, name: str) -> float | None:
    match = re.search(rf"^{re.escape(name)} (\S+)$", text, re.M)
    return float(match[1]) if match else None


def test_the_lab_and_its_broker_report_their_load(stack):
    text = scrape(stack)
    assert sample(text, "actunode_mqtt_connected") == 1
    assert sample(text, "actunode_mqtt_messages_received_total") > 0  # the simulated robots are talking
    assert sample(text, 'actunode_robots{connection="ONLINE"}') >= 1
    # Mosquitto publishes $SYS every 10 s: the broker's heap and clients arrive within a couple of intervals.
    wait_for(lambda: sample(scrape(stack), "actunode_broker_heap_bytes"), 40, "broker statistics in /api/metrics")
    assert sample(scrape(stack), "actunode_broker_clients_connected") >= 2  # at least the backend and a robot
