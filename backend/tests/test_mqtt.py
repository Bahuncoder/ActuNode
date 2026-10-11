import logging

from app import config, mqtt
from app.mqtt import MqttBridge


def bridge():
    def fail(topic, payload, retain):
        raise ValueError("bad")

    return MqttBridge("localhost", 1883, "t", on_message=fail)


class Message:
    topic = "uagv/v2/ActuNode/r/state"
    payload = b"x"
    retain = False


def test_handler_errors_are_rate_limited(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(mqtt.time, "monotonic", lambda: now[0])
    b = bridge()

    with caplog.at_level(logging.ERROR, logger="app.mqtt"):
        for _ in range(5):
            b._on_message(None, None, Message())
        assert len(caplog.records) == 1  # one traceback, four suppressed
        assert caplog.records[0].exc_info

        now[0] += 61
        b._on_message(None, None, Message())

    assert len(caplog.records) == 2
    assert "4 more message handler errors suppressed" in caplog.records[1].getMessage()


def test_default_client_id_is_suffixed_per_process(monkeypatch):
    assert config.settings.mqtt_client_id.startswith("actunode-backend-")
    assert len(config.settings.mqtt_client_id) > len("actunode-backend-")
