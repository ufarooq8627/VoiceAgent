import hmac
import hashlib
import json
import logging
from urllib.parse import urlparse
import httpx

logger = logging.getLogger("app.webhook_dispatcher")

def sign_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"

def is_safe_webhook_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        if hostname.startswith(("169.254.", "10.", "192.168.", "172.16.")):
            return False
        return True
    except Exception:
        return False

def dispatch_lead_webhook(
    webhook_url: str,
    webhook_secret: str,
    payload: dict,
    timeout: float = 3.0
) -> bool:
    if not is_safe_webhook_url(webhook_url):
        logger.warning(f"[Webhook] Rejected unsafe or invalid webhook URL: {webhook_url}")
        return False

    try:
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes, webhook_secret)
        headers = {
            "Content-Type": "application/json",
            "X-Voice-Signature": signature,
            "User-Agent": "DivineVoiceAgent-Webhook/1.0"
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, content=payload_bytes, headers=headers)
            if resp.status_code >= 200 and resp.status_code < 300:
                logger.info(f"[Webhook] Successfully delivered lead to {webhook_url}")
                return True
            else:
                logger.warning(f"[Webhook] Delivery failed with HTTP {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"[Webhook] Exception during webhook delivery to {webhook_url}: {str(e)}")
        return False
