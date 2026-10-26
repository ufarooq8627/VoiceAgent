import pytest
from app.services.voice_synthesis_service import format_speech_payload

def test_format_speech_payload_limits():
    long_text = "This is a very long response that shouldn't drag on in voice. " * 10
    concise = format_speech_payload(long_text, max_chars=120)
    assert len(concise) <= 120
    assert concise.endswith("...")

def test_format_speech_payload_cleans_markdown():
    md_text = "Here is **bold** text and *italic* and `code` with # header."
    clean = format_speech_payload(md_text, max_chars=200)
    assert "*" not in clean
    assert "#" not in clean
    assert "`" not in clean
    assert "bold text" in clean
