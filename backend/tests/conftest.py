import os

# TestClient sends "Host: testserver"; allow it alongside the defaults (see app/security.py, D-24).
os.environ.setdefault("ACTUNODE_ALLOWED_HOSTS", "localhost,127.0.0.1,::1,testserver")


import pytest  # noqa: E402

from app.sent_orders import sent_orders  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_sent_orders():
    sent_orders.clear()
    yield
    sent_orders.clear()


@pytest.fixture(autouse=True)
def _no_dns_for_trusted_proxies(monkeypatch):
    """A lookup of the real proxy name ("frontend") waits for DNS, which can take seconds; a miss now waits for it."""
    from app import auth

    monkeypatch.setattr(auth.trusted_proxies, "refresh", lambda: None)
