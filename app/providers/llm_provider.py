from abc import ABC, abstractmethod
from app.config import settings
from app.schemas.agent import AgentDecision


class BaseLLMProvider(ABC):
    @abstractmethod
    def classify_and_decide(self, prompt: str) -> AgentDecision | None:
        pass


class NoOpLLMProvider(BaseLLMProvider):
    def classify_and_decide(self, prompt: str) -> AgentDecision | None:
        # Phase 1: LLM is disabled
        return None


def get_llm_provider() -> BaseLLMProvider:
    if settings.llm_provider == "none" or not settings.llm_provider:
        return NoOpLLMProvider()
    return NoOpLLMProvider()
