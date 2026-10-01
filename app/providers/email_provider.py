import logging
from abc import ABC, abstractmethod
from app.config import settings

logger = logging.getLogger(__name__)


class BaseEmailProvider(ABC):
    @abstractmethod
    def send(self, to_address: str, subject: str, body_html: str, body_text: str) -> bool:
        pass


class MockEmailProvider(BaseEmailProvider):
    def __init__(self):
        self.sent_emails: list[dict] = []

    def send(self, to_address: str, subject: str, body_html: str, body_text: str) -> bool:
        logger.info(f"[MockEmailProvider] Sending to {to_address} | Subject: {subject}")
        self.sent_emails.append({
            "to": to_address,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
        })
        return True


def get_email_provider() -> BaseEmailProvider:
    if settings.email_provider == "mock":
        return MockEmailProvider()
    return MockEmailProvider()
