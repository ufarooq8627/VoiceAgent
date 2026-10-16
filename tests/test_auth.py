import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app
from app.routes.auth import login_required
from fastapi import HTTPException


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_login_page_renders(client):
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert "Sign in to manage" in response.text


def test_login_invalid_credentials(client):
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Invalid username or password" in response.text


def test_login_success_and_logout(client):
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/"
    assert "recruitment_admin_session" in response.cookies

    # Logout
    logout_res = client.get("/admin/logout", follow_redirects=False)
    assert logout_res.status_code == 303
    assert logout_res.headers["location"] == "/admin/login"


def test_login_required_redirects_html_request(client):
    res = client.get("/admin/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/login"


def test_login_required_htmx_header(client):
    res = client.get("/admin/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers.get("HX-Redirect") == "/admin/login"


@pytest.mark.asyncio
async def test_login_required_api_endpoint_returns_401():
    class DummyRequest:
        def __init__(self, path, session=None, headers=None):
            self.url = type("URL", (), {"path": path})()
            self.session = session or {}
            self.headers = headers or {}

    req_api = DummyRequest("/api/receptionist/calls/start")
    with pytest.raises(HTTPException) as exc_info:
        await login_required(req_api)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication required"
