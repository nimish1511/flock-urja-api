from fastapi.testclient import TestClient


def test_health_healthy(test_client: TestClient):
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["portal_connected"] is True
    assert data["cache_synced"] is True
    assert "timestamp" in data


def test_health_degraded_when_portal_down(test_client: TestClient, mock_client):
    mock_client.portal_alive = False
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["portal_connected"] is False
