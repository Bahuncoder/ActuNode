import sys
import threading

from app import vda5050


def test_header_id_counters_are_capped(monkeypatch):
    monkeypatch.setattr(vda5050, "MAX_HEADER_COUNTERS", 5)
    vda5050._header_ids.clear()

    for i in range(20):
        vda5050.header(f"r{i}", "order")

    assert len(vda5050._header_ids) == 5
    assert vda5050.header("r19", "order")["headerId"] == 2  # recent counters survive
    vda5050._header_ids.clear()


def test_header_ids_are_unique_and_increasing_per_topic_under_threads():
    vda5050._header_ids.clear()
    seen = [[] for _ in range(8)]
    barrier = threading.Barrier(8)

    def hammer(mine):
        barrier.wait()
        for _ in range(500):
            mine.append(vda5050.header("r_thread", "instantActions")["headerId"])

    threads = [threading.Thread(target=hammer, args=(mine,)) for mine in seen]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert all(mine == sorted(mine) for mine in seen)  # each thread sees increasing ids
    assert sorted(i for mine in seen for i in mine) == list(range(1, 4001))  # none repeated or skipped
    vda5050._header_ids.clear()


def test_header_survives_threads_above_the_counter_cap(monkeypatch):
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # switch threads as often as possible
    monkeypatch.setattr(vda5050, "MAX_HEADER_COUNTERS", 3)
    vda5050._header_ids.clear()
    errors = []

    def hammer(n):
        try:
            for i in range(300):
                vda5050.header(f"cap{n}_{i}", "order")
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    sys.setswitchinterval(interval)
    assert errors == []
    assert len(vda5050._header_ids) == 3
    vda5050._header_ids.clear()


def test_order_update_honours_the_stop_map_id_like_an_order_does():
    stitch = {"nodeId": "A", "sequenceId": 2}
    stop = {"nodeId": "B", "x": 1, "y": 2, "mapId": "floor2"}

    update = vda5050.build_order_update("r", "o", 1, stitch, stop)
    order = vda5050.build_order("r", "o", [{**stop, "nodeId": "A"}, stop])

    assert update["nodes"][1]["nodePosition"]["mapId"] == "floor2"
    assert order["nodes"][1]["nodePosition"]["mapId"] == "floor2"


def test_dumps_is_compact_and_keeps_unicode():
    assert vda5050.dumps({"a": [1, 2], "b": "é"}) == '{"a":[1,2],"b":"é"}'


def test_dumps_survives_a_lone_surrogate_from_robot_data():
    """JSON may carry "\\ud800"; such a string cannot be UTF-8 encoded, so the bridge's size check (and the
    broker) would fail on the compact form. Replay republishes recorded robot data, so it must still encode."""
    import json

    from app.vda5050 import dumps

    text = dumps({"mapId": json.loads('"\\ud800x"')})
    text.encode("utf-8")  # must not raise
    assert json.loads(text) == {"mapId": "\ud800x"}
