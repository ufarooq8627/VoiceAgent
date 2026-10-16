import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.routes.auth import login_required

client = TestClient(app)


def test_login_rate_limiting_triggers_429():
    # Limit is 5/minute; 6th or 7th attempt must trigger 429 Too Many Requests
    responses = []
    for _ in range(7):
        res = client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrongpassword"},
            follow_redirects=False,
        )
        responses.append(res.status_code)

    assert 429 in responses, f"Expected HTTP 429 in responses, got {responses}"


def test_receptionist_start_call_rate_limiting_triggers_429():
    app.dependency_overrides[login_required] = lambda: "admin"
    try:
        responses = []
        for _ in range(12):
            res = client.post(
                "/api/receptionist/calls/start",
                json={"dialed_number": "+15550001111", "caller_number": "+15559998888"},
            )
            responses.append(res.status_code)
        assert 429 in responses, f"Expected HTTP 429 in responses, got {responses}"
    finally:
        app.dependency_overrides.pop(login_required, None)
