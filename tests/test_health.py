from fastapi.testclient import TestClient

from core.main import app


def test_agent_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "queue" in data
    assert "redis" in data
