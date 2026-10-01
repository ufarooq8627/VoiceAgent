import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseInboxProvider(ABC):
    @abstractmethod
    def poll(self) -> list[dict]:
        pass


class MockInboxProvider(BaseInboxProvider):
    def poll(self) -> list[dict]:
        # In Phase 1, inbound messages are inserted directly via the Mock Inbox UI
        return []


def get_inbox_provider() -> BaseInboxProvider:
    return MockInboxProvider()
