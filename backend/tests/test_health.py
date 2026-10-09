from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_ok_without_broker():
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "connected" in body["mqtt"]
