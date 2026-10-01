import pytest
from starlette.testclient import TestClient
from datetime import datetime, timezone, timedelta

from app.main import app
from app.config import settings
from app.database import get_db
from app.models import Job, Candidate, Interviewer, Slot, EmailOutbox, Invitation
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.schemas.agent import AgentDecision
from app.agent.worker import agent_tick
from tests.fakes import FakeLLMProvider


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


def test_e2e_webhook_to_booked(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret-e2e")

    # 1. Seed job, interviewer, slots
    job = Job(title="Principal Architect", description="Architecture")
    db_session.add(job)
    interviewer = Interviewer(name="Anil Kumble", email="anil@example.com")
    db_session.add(interviewer)
    db_session.commit()

    cand = Candidate(job_id=job.id, name="Jasprit Bumrah", email="jasprit@example.com", timezone="Asia/Kolkata")
    db_session.add(cand)
    db_session.commit()
    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")

    slots = SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=3),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=3, hours=2),
        duration_minutes=30,
    )
    db_session.commit()

    import hashlib
    raw_token = "valid-secret-token-e2e"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    inv = Invitation(candidate_id=cand.id, token_hash=token_hash, outcome="pending")
    db_session.add(inv)

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[0].id, "B": slots[1].id},
    )
    db_session.add(outbox)
    db_session.commit()

    # 2. Candidate replies via Webhook
    res = client.post(
        "/api/webhooks/incoming-email",
        json={"from_address": cand.email, "subject": "Re: Invitation", "body_text": "I'll take B"},
        headers={"X-Webhook-Secret": "secret-e2e"},
    )
    assert res.status_code == 202

    # 3. Agent tick runs
    class TestSessionFactory:
        def __call__(self):
            return self
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    provider = FakeLLMProvider(AgentDecision(intent="choose", slot_label="B", confidence=0.9))
    agent_tick(session_factory=TestSessionFactory(), provider=provider)

    # 4. Assert candidate is BOOKED and confirmation email sent
    db_session.refresh(cand)
    assert cand.status == CandidateStatus.BOOKED

    db_session.refresh(slots[1])
    assert slots[1].status == "booked"

    conf = db_session.query(EmailOutbox).filter_by(candidate_id=cand.id, kind="confirmation").first()
    assert conf is not None
    assert conf.status == "sent"

    # 5. Accessing token booking page now reflects booked status
    res_page = client.get(f"/i/{raw_token}")
    assert res_page.status_code == 200
    assert "already booked" in res_page.text.lower() or "confirmed" in res_page.text.lower()
