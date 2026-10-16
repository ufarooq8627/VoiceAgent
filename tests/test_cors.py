from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cors_preflight_allowed_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8000"
    assert "access-control-allow-credentials" in response.headers
