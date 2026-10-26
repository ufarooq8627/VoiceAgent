import pytest

def test_static_widget_file_served(client):
    res = client.get("/static/widget/voice-widget.js")
    assert res.status_code == 200
    assert "class VoiceAgentWidget" in res.text or "VoiceAgentWidget" in res.text
    assert "shadowRoot" in res.text
