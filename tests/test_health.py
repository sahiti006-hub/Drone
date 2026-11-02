def test_health_check_endpoint(client):
    """Test that the /api/health endpoint returns a 200 status code and expected JSON payload."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.is_json

    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "Smart Multipurpose Emergency Drone Delivery System"
    assert data["environment"] == "testing"
    assert data["simulation_mode"] is True
    assert "timestamp" in data
    assert "version" in data


def test_root_endpoint(client):
    """Test that the root URL returns 200 OK and points to the health documentation."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.is_json

    data = response.get_json()
    assert "message" in data
    assert data["documentation"] == "/api/health"
