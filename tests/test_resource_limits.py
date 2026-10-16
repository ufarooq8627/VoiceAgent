import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.routes.auth import login_required


@pytest.fixture
def auth_client():
    app.dependency_overrides[login_required] = lambda: "admin"
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(login_required, None)


def test_audio_upload_exceeding_10mb_returns_413(auth_client):
    # Create fake audio payload larger than 10MB (10MB + 1024 bytes)
    oversized_data = b"0" * (10 * 1024 * 1024 + 1024)
    file_obj = io.BytesIO(oversized_data)
    response = auth_client.post(
        "/api/receptionist/calls/fake-call-id/audio-turn",
        files={"audio": ("test.webm", file_obj, "audio/webm")},
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()
