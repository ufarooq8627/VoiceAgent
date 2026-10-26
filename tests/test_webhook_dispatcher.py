import pytest
import hmac
import hashlib
import json
from unittest.mock import patch, MagicMock
from app.services.webhook_dispatcher import dispatch_lead_webhook, sign_webhook_payload, is_safe_webhook_url

def test_sign_webhook_payload():
    payload = {"event": "lead.callback", "number": "+15551234567"}
    secret = "whsec_test_secret_123"
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    signature = sign_webhook_payload(payload_bytes, secret)
    assert signature == f"sha256={expected}"

def test_is_safe_webhook_url():
    assert is_safe_webhook_url("https://api.myclientcrm.com/webhooks/voice") is True
    assert is_safe_webhook_url("http://localhost:8000/hook") is False
    assert is_safe_webhook_url("http://127.0.0.1/hook") is False
    assert is_safe_webhook_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_webhook_url("ftp://not-http.com") is False

@patch("httpx.Client.post")
def test_dispatch_lead_webhook_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    payload = {"customer_name": "John Doe", "callback_number": "+15550009999"}
    success = dispatch_lead_webhook(
        webhook_url="https://api.zapier.com/hooks/catch/123/abc",
        webhook_secret="whsec_123",
        payload=payload
    )
    assert success is True
    assert mock_post.called
    kwargs = mock_post.call_args[1]
    assert "X-Voice-Signature" in kwargs["headers"]
    assert kwargs["headers"]["X-Voice-Signature"].startswith("sha256=")

@patch("httpx.Client.post")
def test_dispatch_lead_webhook_handles_timeout_gracefully(mock_post):
    import httpx
    mock_post.side_effect = httpx.TimeoutException("Connection timed out")

    payload = {"customer_name": "Alice"}
    success = dispatch_lead_webhook(
        webhook_url="https://slow-server.com/hook",
        webhook_secret="whsec_123",
        payload=payload
    )
    assert success is False  # Does not crash or raise exception
