from app import vda5050


def test_header_id_counters_are_capped(monkeypatch):
    monkeypatch.setattr(vda5050, "MAX_HEADER_COUNTERS", 5)
    vda5050._header_ids.clear()

    for i in range(20):
        vda5050.header(f"r{i}", "order")

    assert len(vda5050._header_ids) == 5
    assert vda5050.header("r19", "order")["headerId"] == 2  # recent counters survive
    vda5050._header_ids.clear()
