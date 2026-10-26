import time
import json
import base64
import hmac
import hashlib
from typing import Dict, Any
from app.config import settings

def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64_decode(s: str) -> bytes:
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + padding)

def mint_widget_session_token(business_id: str, origin: str, client_ip: str, ttl_seconds: int = 900) -> str:
    now = int(time.time())
    payload = {
        "business_id": business_id,
        "origin": origin,
        "client_ip": client_ip,
        "iat": now,
        "exp": now + ttl_seconds
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)
    secret = settings.app_secret_key.encode("utf-8")
    sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64_encode(sig)
    return f"{payload_b64}.{sig_b64}"

def verify_widget_session_token(token: str) -> Dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("Malformed token format")
        payload_b64, sig_b64 = parts
        secret = settings.app_secret_key.encode("utf-8")
        expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = _b64_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Invalid token signature")
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("Token expired")
        return payload
    except Exception as e:
        raise ValueError(f"Token validation failed: {str(e)}")
