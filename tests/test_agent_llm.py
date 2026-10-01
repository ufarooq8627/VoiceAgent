from types import SimpleNamespace
import pytest
from app.config import settings
from app.schemas.agent import AgentDecision
from app.providers.llm_provider import (
    GeminiLLMProvider,
    NoOpLLMProvider,
    LLMTransientError,
    LLMPermanentError,
)


class MockAPIError(Exception):
    def __init__(self, code, message="API error"):
        self.code = code
        super().__init__(message)


@pytest.fixture
def fake_context():
    return {
        "candidate_id": "c-uuid-1234-5678",
        "email": "nikhil@secret-domain.com",
        "phone": "+91 9876543210",
        "first_name": "Nikhil",
        "job_title": "Distributed Systems Engineer",
        "offered_slots": [
            {"label": "A", "when": "Mon 05 Oct, 10:00 AM UTC", "mode": "virtual"},
            {"label": "B", "when": "Mon 05 Oct, 11:00 AM UTC", "mode": "virtual"},
        ],
        "history": [
            {"direction": "outbound", "summary": "Sent invitation with 2 slots"}
        ],
    }


def test_gemini_returns_decision(fake_context, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "fake-key")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    provider = GeminiLLMProvider()

    expected = AgentDecision(intent="choose", slot_label="A", confidence=0.95, reason="Candidate picked A")
    fake_resp = SimpleNamespace(parsed=expected, text="")

    monkeypatch.setattr(provider._client.models, "generate_content", lambda **kwargs: fake_resp)

    decision = provider.classify("Slot A please", fake_context)
    assert decision.intent == "choose"
    assert decision.slot_label == "A"
    assert decision.confidence == 0.95


def test_falls_back_to_text_json(fake_context, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "fake-key")
    provider = GeminiLLMProvider()

    fake_resp = SimpleNamespace(
        parsed=None,
        text='{"intent":"decline","confidence":0.9,"reason":"not interested"}'
    )
    monkeypatch.setattr(provider._client.models, "generate_content", lambda **kwargs: fake_resp)

    decision = provider.classify("I decline", fake_context)
    assert decision.intent == "decline"
    assert decision.confidence == 0.9


def test_malformed_output_is_permanent_error(fake_context, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "fake-key")
    provider = GeminiLLMProvider()

    fake_resp = SimpleNamespace(parsed=None, text="not json at all")
    monkeypatch.setattr(provider._client.models, "generate_content", lambda **kwargs: fake_resp)

    with pytest.raises(LLMPermanentError):
        provider.classify("hi", fake_context)


@pytest.mark.parametrize("exc,expected_error_type", [
    (MockAPIError(429), LLMTransientError),
    (MockAPIError(500), LLMTransientError),
    (MockAPIError(503), LLMTransientError),
    (TimeoutError("timed out"), LLMTransientError),
    (MockAPIError(400), LLMPermanentError),
    (MockAPIError(403), LLMPermanentError),
])
def test_transient_classification(fake_context, monkeypatch, exc, expected_error_type):
    monkeypatch.setattr(settings, "llm_api_key", "fake-key")
    provider = GeminiLLMProvider()

    def raise_exc(**kwargs):
        raise exc

    monkeypatch.setattr(provider._client.models, "generate_content", raise_exc)

    with pytest.raises(expected_error_type):
        provider.classify("Slot A", fake_context)


def test_prompt_excludes_pii(fake_context, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "fake-key")
    provider = GeminiLLMProvider()

    captured_kwargs = {}

    def capture_content(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            parsed=AgentDecision(intent="choose", slot_label="A", confidence=0.9),
            text=""
        )

    monkeypatch.setattr(provider._client.models, "generate_content", capture_content)

    provider.classify("Slot A", fake_context)

    prompt = captured_kwargs.get("contents", "")
    assert fake_context["candidate_id"] not in prompt
    assert fake_context["email"] not in prompt
    assert fake_context["phone"] not in prompt
    assert "Nikhil" in prompt
    assert "Slot A" in prompt
    assert "Mon 05 Oct, 10:00 AM UTC" in prompt


def test_noop_provider_raises_permanent(fake_context):
    provider = NoOpLLMProvider()
    with pytest.raises(LLMPermanentError):
        provider.classify("hi", fake_context)
