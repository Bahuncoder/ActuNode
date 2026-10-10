import json

from app.live import LiveHub
from app.proximity import ProximityMonitor


def state(x, y, map_id="warehouse", v3=False):
    key = "mobileRobotPosition" if v3 else "agvPosition"
    return {key: {"x": x, "y": y, "theta": 0, "mapId": map_id}}


def test_near_miss_is_reported_once_until_the_robots_separate():
    monitor = ProximityMonitor(min_distance=1.0, now=lambda: 0.0)

    assert monitor.observe("a", state(0, 0)) == []
    [first] = monitor.observe("b", state(0.6, 0))
    again = monitor.observe("b", state(0.5, 0))
    apart = monitor.observe("b", state(1.3, 0))  # beyond the 1.2 m re-arm distance
    second = monitor.observe("b", state(0.4, 0))

    assert first["rule"] == "proximity" and first["severity"] == "warning"
    assert "a" in first["message"] and "0.6" in first["message"]
    assert first["path"] == "/agvPosition"
    assert again == [] and apart == []
    assert len(second) == 1
    assert monitor.active_pairs() == [{"robots": ["a", "b"], "distance": 0.4}]


def test_hovering_near_the_limit_does_not_flood():
    monitor = ProximityMonitor(min_distance=1.0, now=lambda: 0.0)
    monitor.observe("a", state(0, 0))

    reports = [monitor.observe("b", state(x, 0)) for x in (0.9, 1.05, 0.95, 1.1, 0.9)]

    assert sum(len(r) for r in reports) == 1


def test_works_with_3_0_positions_and_ignores_other_maps():
    monitor = ProximityMonitor(min_distance=1.0, now=lambda: 0.0)
    monitor.observe("a", state(0, 0, v3=True))

    assert monitor.observe("b", state(0.2, 0, map_id="other-floor")) == []
    [issue] = monitor.observe("c", state(0.2, 0, v3=True))
    assert issue["path"] == "/mobileRobotPosition"


def test_stale_and_offline_robots_do_not_count():
    clock = {"t": 0.0}
    monitor = ProximityMonitor(min_distance=1.0, stale_after=3.0, now=lambda: clock["t"])
    monitor.observe("silent", state(0, 0))
    monitor.observe("gone", state(5, 5))
    monitor.forget("gone")  # e.g. CONNECTIONBROKEN

    clock["t"] = 10.0
    assert monitor.observe("b", state(0.1, 0)) == []  # 'silent' last reported 10 s ago
    assert monitor.observe("c", state(5.1, 5)) == []


def test_malformed_positions_are_ignored():
    monitor = ProximityMonitor(min_distance=1.0, now=lambda: 0.0)
    monitor.observe("a", state(0, 0))

    assert monitor.observe("b", {"agvPosition": {"x": "near", "y": 0, "mapId": "warehouse"}}) == []
    assert monitor.observe("b", {"agvPosition": None}) == []


def test_hub_attaches_the_warning_counts_it_and_reports_active_pairs():
    hub = LiveHub()
    for serial, x in (("r1", 0.0), ("r2", 0.5)):
        hub.handle_mqtt(
            f"uagv/v2/ActuNode/{serial}/state", json.dumps({"serialNumber": serial, **state(x, 0)}).encode()
        )

    last = hub.snapshot()["messages"][-1]
    assert "proximity" in [issue["rule"] for issue in last["issues"]]
    assert any(rule["rule"] == "proximity" for rule in hub.validation()["byRule"])
    assert hub.snapshot()["proximity"] == [{"robots": ["r1", "r2"], "distance": 0.5}]


def test_disconnect_removes_the_robot_from_proximity():
    hub = LiveHub()
    hub.handle_mqtt("uagv/v2/ActuNode/r1/state", json.dumps(state(0, 0)).encode())
    hub.handle_mqtt("uagv/v2/ActuNode/r2/state", json.dumps(state(0.5, 0)).encode())

    hub.handle_mqtt("uagv/v2/ActuNode/r2/connection", b'{"connectionState": "CONNECTIONBROKEN"}')

    assert hub.snapshot()["proximity"] == []
