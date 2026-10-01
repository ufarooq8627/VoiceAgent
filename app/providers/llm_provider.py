from abc import ABC, abstractmethod
from google import genai
from google.genai import types

from app.config import settings
from app.schemas.agent import AgentDecision
from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt


class LLMTransientError(Exception):
    pass


class LLMPermanentError(Exception):
    pass


class BaseLLMProvider(ABC):
    @abstractmethod
    def classify(self, email_text: str, context: dict) -> AgentDecision:
        pass


class NoOpLLMProvider(BaseLLMProvider):
    def classify(self, email_text: str, context: dict) -> AgentDecision:
        raise LLMPermanentError("llm_disabled")

    # Backwards compatibility with Phase 1
    def classify_and_decide(self, prompt: str) -> AgentDecision | None:
        return None


class GeminiLLMProvider(BaseLLMProvider):
    def __init__(self):
        self._client = genai.Client(
            api_key=settings.llm_api_key,
            http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
        )

    def classify(self, email_text: str, context: dict) -> AgentDecision:
        try:
            resp = self._client.models.generate_content(
                model=settings.llm_model,
                contents=build_user_prompt(email_text, context),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=AgentDecision,
                    temperature=0,
                ),
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(exc, TimeoutError) or code in (408, 429, 500, 502, 503, 504):
                raise LLMTransientError(f"{type(exc).__name__}:{code}") from None
            raise LLMPermanentError(f"{type(exc).__name__}:{code}") from None

        try:
            return resp.parsed if isinstance(resp.parsed, AgentDecision) \
                else AgentDecision.model_validate_json(resp.text)
        except Exception as exc:
            raise LLMPermanentError(f"bad_output:{type(exc).__name__}") from None


def get_llm_provider() -> BaseLLMProvider:
    if settings.llm_provider == "gemini":
        return GeminiLLMProvider()
    return NoOpLLMProvider()
