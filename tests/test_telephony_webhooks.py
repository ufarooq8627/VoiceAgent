import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_twilio_inbound_voice_returns_twiml():
    sid = f"CA_inbound_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/telephony/twilio/voice",
        data={
            "CallSid": sid,
            "From": "+19998887777",
            "To": "+15550001111",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    xml_text = response.text
    assert "<Response>" in xml_text
    assert "<Gather" in xml_text
    assert "Polly.Joanna-Neural" in xml_text
    assert "Apex Dental &amp; Wellness Clinic" in xml_text


def test_twilio_gather_speech_triggers_agent():
    sid = f"CA_turn_{uuid.uuid4().hex[:8]}"
    # 1. Inbound first
    client.post(
        "/api/telephony/twilio/voice",
        data={
            "CallSid": sid,
            "From": "+19998887777",
            "To": "+15550001111",
        },
    )

    # 2. Caller speaks: "What are your opening hours?"
    response = client.post(
        f"/api/telephony/twilio/gather?call_sid={sid}",
        data={
            "SpeechResult": "What are your opening hours?",
            "Confidence": 0.95,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    xml_text = response.text
    assert "<Response>" in xml_text
    assert "<Say" in xml_text
    assert "8:30 AM" in xml_text or "Monday" in xml_text


def test_twilio_status_callback_completes_call():
    sid = f"CA_status_{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/telephony/twilio/voice",
        data={
            "CallSid": sid,
            "From": "+19998887777",
            "To": "+15550001111",
        },
    )

    response = client.post(
        "/api/telephony/twilio/status",
        data={
            "CallSid": sid,
            "CallStatus": "completed",
            "CallDuration": "45",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_telnyx_inbound_voice_returns_texml():
    sid = f"v3:telnyx_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/telephony/telnyx/voice",
        data={
            "CallSid": sid,
            "From": "+19998887777",
            "To": "+15550001111",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    xml_text = response.text
    assert "<Response>" in xml_text
    assert "<Gather" in xml_text
    assert "Apex Dental &amp; Wellness Clinic" in xml_text


def test_telnyx_gather_speech_triggers_agent():
    sid = f"v3:telnyx_turn_{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/telephony/telnyx/voice",
        data={
            "CallSid": sid,
            "From": "+19998887777",
            "To": "+15550001111",
        },
    )

    response = client.post(
        f"/api/telephony/telnyx/gather?call_sid={sid}",
        data={
            "SpeechResult": "Where are you located?",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert "<Say" in response.text
