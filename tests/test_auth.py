import pytest
from fastapi.testclient import TestClient
from app.main import app


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
