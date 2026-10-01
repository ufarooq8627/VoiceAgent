import pytest
from starlette.testclient import TestClient
from datetime import datetime, timezone, timedelta

from app.main import app
from app.config import settings
from app.database import get_db
from app.models import Job, Candidate, Interviewer, Invitation, InboundMessage, ConversationMessage
from app.services.state_machine import transition_candidate, CandidateStatus


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def webhook_cand(db_session):
    job = Job(title="Data Scientist", description="ML/NLP")
    db_session.add(job)
    db_session.commit()

    cand = Candidate(
        job_id=job.id,
        name="Rohit Sharma",
        email="rohit@example.com",
    )
    db_session.add(cand)
    db_session.commit()
    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")

    inv = Invitation(candidate_id=cand.id, token_hash="hash-1", outcome="pending")
    db_session.add(inv)
    db_session.commit()
    return cand


def test_webhook_auth_failures(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-123")

    # Missing header
    res1 = client.post("/api/webhooks/incoming-email", json={
        "from_address": "test@x.com",
        "body_text": "hello",
    })
    assert res1.status_code == 401

    # Wrong secret
    res2 = client.post("/api/webhooks/incoming-email", json={
        "from_address": "test@x.com",
        "body_text": "hello",
    }, headers={"X-Webhook-Secret": "wrong"})
    assert res2.status_code == 401


def test_webhook_disabled_when_secret_empty(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "")
    res = client.post("/api/webhooks/incoming-email", json={
        "from_address": "test@x.com",
        "body_text": "hello",
    }, headers={"X-Webhook-Secret": "secret-123"})
    assert res.status_code in (401, 404)


def test_webhook_success_creates_inbound_and_conv(client, db_session, webhook_cand, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-123")

    res = client.post(
        "/api/webhooks/incoming-email",
        json={
            "from_address": "ROHIT@example.com",  # case-insensitive
            "subject": "Re: Invitation",
            "body_text": "I pick slot A",
        },
        headers={"X-Webhook-Secret": "secret-123"},
    )
    assert res.status_code == 202
    assert res.json() == {"status": "accepted"}

    msg = db_session.query(InboundMessage).filter_by(candidate_id=webhook_cand.id).first()
    assert msg is not None
    assert msg.processed is False
    assert msg.body_text == "I pick slot A"

    conv = db_session.query(ConversationMessage).filter_by(candidate_id=webhook_cand.id, direction="inbound").first()
    assert conv is not None


def test_webhook_unknown_sender(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-123")

    res = client.post(
        "/api/webhooks/incoming-email",
        json={
            "from_address": "unknown@stranger.com",
            "body_text": "Who are you?",
        },
        headers={"X-Webhook-Secret": "secret-123"},
    )
    assert res.status_code == 202

    msg = db_session.query(InboundMessage).filter_by(from_address="unknown@stranger.com").first()
    assert msg is not None
    assert msg.candidate_id is None
    assert msg.processed is True
    assert msg.agent_result == {"action": "unmatched"}


def test_webhook_dedupe_message_id(client, db_session, webhook_cand, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-123")

    payload = {
        "from_address": webhook_cand.email,
        "body_text": "I choose A",
        "headers": {"Message-ID": "<unique-msg-123@domain.com>"},
    }
    res1 = client.post("/api/webhooks/incoming-email", json=payload, headers={"X-Webhook-Secret": "secret-123"})
    assert res1.status_code == 202

    # Second post with identical Message-ID returns 202 but creates no second row
    res2 = client.post("/api/webhooks/incoming-email", json=payload, headers={"X-Webhook-Secret": "secret-123"})
    assert res2.status_code == 202

    count = db_session.query(InboundMessage).filter_by(message_id="<unique-msg-123@domain.com>").count()
    assert count == 1


def test_webhook_body_too_large(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-123")
    huge_body = "A" * 20001
    res = client.post(
        "/api/webhooks/incoming-email",
        json={"from_address": "test@x.com", "body_text": huge_body},
        headers={"X-Webhook-Secret": "secret-123"},
    )
    assert res.status_code == 422
