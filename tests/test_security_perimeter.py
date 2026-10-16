from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)


def test_perimeter_receptionist_admin_routes_locked():
    """Verify all receptionist admin routes reject unauthenticated access with 303 redirect."""
    routes = [
        ("GET", "/admin/receptionist/enquiries"),
        ("GET", "/admin/receptionist/export"),
        ("GET", "/admin/receptionist/export/csv"),
        ("GET", "/admin/receptionist/export/json"),
        ("GET", "/admin/receptionist/export/xlsx"),
        ("POST", "/admin/receptionist/enquiries/fake-id/resolve"),
    ]
    for method, path in routes:
        res = client.request(method, path, follow_redirects=False)
        assert res.status_code == 303, f"{path} returned status {res.status_code} instead of 303 redirect"
        assert res.headers["location"] == "/admin/login", f"{path} did not redirect to /admin/login"


def test_perimeter_mock_call_and_api_locked():
    """Verify mock-call page redirects and receptionist call APIs return 401 Unauthorized."""
    # Mock call page (HTML) -> 303 redirect
    res_page = client.get("/admin/mock-call", follow_redirects=False)
    assert res_page.status_code == 303
    assert res_page.headers["location"] == "/admin/login"

    # API Endpoints (JSON) -> 401 Unauthorized
    res_start = client.post(
        "/api/receptionist/calls/start",
        json={"dialed_number": "+15550001111", "caller_number": "+19998887777"},
    )
    assert res_start.status_code == 401
    assert res_start.json()["detail"] == "Authentication required"

    res_turn = client.post(
        "/api/receptionist/calls/fake-id/turn",
        json={"caller_message": "test"},
    )
    assert res_turn.status_code == 401
    assert res_turn.json()["detail"] == "Authentication required"

    res_end = client.post(
        "/api/receptionist/calls/fake-id/end",
        json={"summary": "done"},
    )
    assert res_end.status_code == 401
    assert res_end.json()["detail"] == "Authentication required"


def test_perimeter_telephony_webhooks_locked():
    """Verify telephony webhooks reject unauthenticated requests without valid token."""
    paths = [
        "/api/telephony/twilio/voice",
        "/api/telephony/twilio/gather?call_sid=123",
        "/api/telephony/twilio/status",
        "/api/telephony/telnyx/voice",
        "/api/telephony/telnyx/gather?call_sid=123",
        "/api/telephony/telnyx/status",
    ]
    for p in paths:
        res = client.post(p, data={})
        assert res.status_code == 403, f"{p} allowed unauthenticated access (returned {res.status_code})"

    # Positive check: with valid token header, status callback route allows access
    res_valid = client.post(
        "/api/telephony/twilio/status",
        headers={"X-Telephony-Token": settings.telephony_webhook_token},
        data={"CallSid": "dummy-sid", "CallStatus": "completed"},
    )
    assert res_valid.status_code == 200
