import pytest
from datetime import datetime, timezone, timedelta
from starlette.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import get_db
from app.models import Job, Interviewer, Candidate, Slot, EmailOutbox, InboundMessage, CandidateEvent
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService


@pytest.fixture
def auth_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        # Log in as admin
        res = client.post(
            "/admin/login",
            data={"username": settings.admin_username, "password": "admin123"},
            follow_redirects=False,
        )
        assert res.status_code == 303
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def job_and_candidate(db_session):
    job = Job(title="Lead DevOps Engineer", description="K8s, Terraform")
    db_session.add(job)
    interviewer = Interviewer(name="Zaheer Khan", email="zaheer@example.com")
    db_session.add(interviewer)
    db_session.commit()

    cand = Candidate(
        job_id=job.id,
        name="Harbhajan Singh",
        email="bhajji@example.com",
        timezone="Asia/Kolkata",
    )
    db_session.add(cand)
    db_session.commit()

    slots = SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, hours=2),
        duration_minutes=30,
    )
    db_session.commit()

    return job, cand, slots


def test_conversations_shows_agent_result_and_ignored_after_close(auth_client, db_session, job_and_candidate):
    job, cand, slots = job_and_candidate

    # Inbound message 1 with decision result
    msg1 = InboundMessage(
        candidate_id=cand.id,
        from_address=cand.email,
        subject="Re: Interview",
        body_text="I choose slot A",
        processed=True,
        agent_result={"action": "booked", "intent": "choose", "confidence": 0.95, "slot_label": "A"},
    )
    db_session.add(msg1)

    # Inbound message 2 after close
    msg2 = InboundMessage(
        candidate_id=cand.id,
        from_address=cand.email,
        subject="Re: Interview again",
        body_text="Can I switch?",
        processed=True,
        agent_result={"action": "ignored_status"},
    )
    db_session.add(msg2)

    ev = CandidateEvent(
        candidate_id=cand.id,
        event_type="inbound_after_close",
        actor="agent",
        payload={"inbound_id": msg2.id},
    )
    db_session.add(ev)
    db_session.commit()

    res = auth_client.get(f"/admin/candidates/{cand.id}/conversations")
    assert res.status_code == 200
    text = res.text.lower()
    assert "booked" in text
    assert "choose" in text
    assert "0.95" in text or "95%" in text
    assert "ignored after close" in text


def test_job_detail_filter_pill_and_inbound_after_close_badge(auth_client, db_session, job_and_candidate):
    job, cand, slots = job_and_candidate

    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, cand.id, CandidateStatus.NEEDS_RECRUITER, "agent")
    db_session.commit()

    ev = CandidateEvent(
        candidate_id=cand.id,
        event_type="inbound_after_close",
        actor="agent",
        payload={},
    )
    db_session.add(ev)
    db_session.commit()

    # Filter by NEEDS_RECRUITER
    res_filter = auth_client.get(f"/admin/jobs/{job.id}?tab=candidates&status=NEEDS_RECRUITER")
    assert res_filter.status_code == 200
    assert cand.name in res_filter.text
    assert "ignored after close" in res_filter.text.lower() or "reply after close" in res_filter.text.lower()


def test_recruiter_reinvite(auth_client, db_session, job_and_candidate):
    job, cand, slots = job_and_candidate

    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, cand.id, CandidateStatus.NEEDS_RECRUITER, "agent")
    db_session.commit()

    res = auth_client.post(f"/admin/candidates/{cand.id}/reinvite", follow_redirects=False)
    assert res.status_code == 303

    db_session.refresh(cand)
    assert cand.status == CandidateStatus.INVITED

    new_invite = db_session.query(EmailOutbox).filter_by(candidate_id=cand.id, kind="invitation").order_by(EmailOutbox.created_at.desc()).first()
    assert new_invite is not None
    assert new_invite.offered_slots is not None
    assert "A" in new_invite.offered_slots


def test_recruiter_manual_booking(auth_client, db_session, job_and_candidate):
    job, cand, slots = job_and_candidate

    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, cand.id, CandidateStatus.NEEDS_RECRUITER, "agent")
    db_session.commit()

    slot_to_book = slots[0]
    res = auth_client.post(
        f"/admin/candidates/{cand.id}/manual-book",
        data={"slot_id": slot_to_book.id},
        follow_redirects=False,
    )
    assert res.status_code == 303

    db_session.refresh(cand)
    assert cand.status == CandidateStatus.BOOKED

    db_session.refresh(slot_to_book)
    assert slot_to_book.status == "booked"


def test_hx_request_fragment_and_vary_header(auth_client, db_session, job_and_candidate):
    job, cand, slots = job_and_candidate

    # Full page request
    res_full = auth_client.get(f"/admin/candidates/{cand.id}/conversations")
    assert res_full.status_code == 200
    assert "<!DOCTYPE html>" in res_full.text
    assert "HX-Request" in res_full.headers.get("Vary", "")

    # Partial / HTMX request
    res_frag = auth_client.get(
        f"/admin/candidates/{cand.id}/conversations",
        headers={"HX-Request": "true"},
    )
    assert res_frag.status_code == 200
    assert "<!DOCTYPE html>" not in res_frag.text
    assert "candidate-history-page" in res_frag.text
    assert "HX-Request" in res_frag.headers.get("Vary", "")


def test_mock_inbox_disabled_and_auth(auth_client, unauth_client, monkeypatch):
    # Unauthenticated redirect
    res_unauth = unauth_client.get("/admin/mock-inbox", follow_redirects=False)
    assert res_unauth.status_code in (303, 307)
    assert "/admin/login" in res_unauth.headers.get("location", "")

    # Authenticated but mock_inbox disabled
    monkeypatch.setattr(settings, "mock_inbox", False)
    res_disabled = auth_client.get("/admin/mock-inbox")
    assert res_disabled.status_code == 403
