from datetime import datetime, timezone, timedelta
import pytest
from app.models import Job, Candidate, Interviewer, Slot, Booking, EmailOutbox, Invitation, CandidateEvent
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.agent.tools import AgentTools


@pytest.fixture
def tools_setup(db_session):
    job = Job(title="Systems Architect", description="Distributed computing")
    db_session.add(job)
    interviewer = Interviewer(name="Vikram Seth", email="vikram@example.com")
    db_session.add(interviewer)
    db_session.commit()

    cand = Candidate(
        job_id=job.id,
        name="Ananya Roy",
        email="ananya@example.com",
        phone="+91 9999999999",
        timezone="Asia/Kolkata",
    )
    db_session.add(cand)
    db_session.commit()
    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")

    # Create 3 slots
    slots = SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, hours=1, minutes=30),
        duration_minutes=30,
    )
    db_session.commit()

    # Create an invitation record
    inv = Invitation(candidate_id=cand.id, token_hash="dummy-hash-123", outcome="pending")
    db_session.add(inv)
    db_session.commit()

    return job, cand, slots, interviewer


def test_active_offer_uses_last_sent_not_queued(db_session, tools_setup):
    _, cand, slots, _ = tools_setup

    out_sent = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
        offered_slots={"A": slots[0].id, "B": slots[1].id},
    )
    out_queued = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation 2",
        body_html="<p>invite</p>",
        body_text="invite",
        status="queued",
        offered_slots={"A": slots[2].id},
    )
    db_session.add_all([out_sent, out_queued])
    db_session.commit()

    tools = AgentTools(db_session, cand.id)
    offer = tools.active_offer()
    assert offer == {"A": slots[0].id, "B": slots[1].id}


def test_book_resolves_via_snapshot_not_fresh_labels(db_session, tools_setup):
    job, cand, slots, interviewer = tools_setup
    s1, s2, s3 = slots[0], slots[1], slots[2]

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": s1.id, "B": s2.id, "C": s3.id},
    )
    db_session.add(outbox)
    db_session.commit()

    other_cand = Candidate(job_id=job.id, name="Other", email="other@x.com")
    db_session.add(other_cand)
    db_session.commit()
    transition_candidate(db_session, other_cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, other_cand.id, CandidateStatus.INVITED, "system")
    SlotService.book(db_session, s1.id, other_cand.id, commit=True)

    tools = AgentTools(db_session, cand.id)
    res = tools.book_slot("B")
    assert res["success"] is True

    db_session.commit()
    db_session.refresh(s2)
    assert s2.status == "booked"
    booking = db_session.query(Booking).filter_by(slot_id=s2.id).first()
    assert booking.candidate_id == cand.id


def test_book_taken_slot_returns_slot_taken(db_session, tools_setup):
    job, cand, slots, _ = tools_setup
    s1, s2 = slots[0], slots[1]

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": s1.id, "B": s2.id},
    )
    db_session.add(outbox)
    db_session.commit()

    other = Candidate(job_id=job.id, name="Other", email="o@x.com")
    db_session.add(other)
    db_session.commit()
    transition_candidate(db_session, other.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, other.id, CandidateStatus.INVITED, "system")
    SlotService.book(db_session, s2.id, other.id, commit=True)

    tools = AgentTools(db_session, cand.id)
    res = tools.book_slot("B")
    assert res["success"] is False
    assert res["reason"] == "slot_taken"
    db_session.refresh(cand)
    assert cand.status == CandidateStatus.INVITED


def test_book_unknown_label(db_session, tools_setup):
    _, cand, slots, _ = tools_setup
    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[0].id},
    )
    db_session.add(outbox)
    db_session.commit()

    tools = AgentTools(db_session, cand.id)
    res = tools.book_slot("Z")
    assert res["success"] is False
    assert res["reason"] == "unknown_label"


def test_book_success_sets_everything_uncommitted(db_session, tools_setup):
    _, cand, slots, _ = tools_setup
    s1 = slots[0]

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": s1.id},
    )
    db_session.add(outbox)
    db_session.commit()

    tools = AgentTools(db_session, cand.id)
    res = tools.book_slot("A")
    assert res["success"] is True

    db_session.rollback()
    db_session.refresh(s1)
    assert s1.status == "open"
    db_session.refresh(cand)
    assert cand.status == CandidateStatus.INVITED

    tools = AgentTools(db_session, cand.id)
    res2 = tools.book_slot("A")
    assert res2["success"] is True
    db_session.commit()

    db_session.refresh(s1)
    assert s1.status == "booked"
    db_session.refresh(cand)
    assert cand.status == CandidateStatus.BOOKED

    inv = db_session.query(Invitation).filter_by(candidate_id=cand.id).first()
    assert inv.outcome == "booked"

    conf_mail = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.candidate_id == cand.id, EmailOutbox.kind == "confirmation")
        .first()
    )
    assert conf_mail is not None
    assert conf_mail.status == "queued"


def test_book_rolls_back_if_transition_illegal(db_session, tools_setup):
    _, cand, slots, _ = tools_setup
    s1 = slots[0]

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": s1.id},
    )
    db_session.add(outbox)
    transition_candidate(db_session, cand.id, CandidateStatus.DECLINED, "agent")
    db_session.commit()

    tools = AgentTools(db_session, cand.id)
    res = tools.book_slot("A")
    assert res["success"] is False
    assert res["reason"] == "illegal_state"

    db_session.refresh(s1)
    assert s1.status == "open"


def test_escalate_transitions_and_queues_ack(db_session, tools_setup):
    _, cand, _, _ = tools_setup
    tools = AgentTools(db_session, cand.id)
    tools.escalate_to_recruiter("Candidate asked a salary question")
    db_session.commit()

    db_session.refresh(cand)
    assert cand.status == CandidateStatus.NEEDS_RECRUITER

    ack_mail = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.candidate_id == cand.id, EmailOutbox.kind == "escalation_ack")
        .first()
    )
    assert ack_mail is not None


def test_escalate_without_notify(db_session, tools_setup):
    _, cand, _, _ = tools_setup
    tools = AgentTools(db_session, cand.id)
    tools.escalate_to_recruiter("Quiet escalation", notify_candidate=False)
    db_session.commit()

    db_session.refresh(cand)
    assert cand.status == CandidateStatus.NEEDS_RECRUITER

    ack_mail = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.candidate_id == cand.id, EmailOutbox.kind == "escalation_ack")
        .first()
    )
    assert ack_mail is None


def test_context_has_no_pii(db_session, tools_setup):
    _, cand, slots, _ = tools_setup
    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Invitation",
        body_html="<p>invite</p>",
        body_text="invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[0].id},
    )
    db_session.add(outbox)
    db_session.commit()

    tools = AgentTools(db_session, cand.id)
    ctx = tools.get_candidate_context()

    assert "email" not in ctx
    assert "phone" not in ctx
    assert "candidate_id" not in ctx
    assert cand.email not in str(ctx)
    assert cand.phone not in str(ctx)
    assert cand.id not in str(ctx)
    assert "first_name" in ctx
    assert "offered_slots" in ctx
    assert "history" in ctx
