import os
import pytest
import threading
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Job, Interviewer, Candidate, Slot, Booking, EmailOutbox, InboundMessage, Invitation
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.agent.loop import process_candidate_messages
from app.schemas.agent import AgentDecision
from tests.fakes import FakeLLMProvider
from app.config import settings


def make_file_db(tmp_path):
    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def test_concurrency_two_candidates_competing_for_same_slot(tmp_path):
    engine, SessionFactory = make_file_db(tmp_path)
    main_session = SessionFactory()

    job = Job(title="Concurrency Architect", description="Distributed computing")
    main_session.add(job)
    interviewer = Interviewer(name="Ravi Shastri", email="ravi@example.com")
    main_session.add(interviewer)
    main_session.commit()

    cand1 = Candidate(job_id=job.id, name="Candidate Alpha", email="alpha@example.com", timezone="Asia/Kolkata")
    cand2 = Candidate(job_id=job.id, name="Candidate Beta", email="beta@example.com", timezone="Asia/Kolkata")
    main_session.add_all([cand1, cand2])
    main_session.commit()

    transition_candidate(main_session, cand1.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(main_session, cand1.id, CandidateStatus.INVITED, "system")
    transition_candidate(main_session, cand2.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(main_session, cand2.id, CandidateStatus.INVITED, "system")

    # Single open slot
    slot = Slot(
        job_id=job.id,
        interviewer_id=interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, minutes=30),
        status="open",
        mode="video",
    )
    main_session.add(slot)
    main_session.commit()

    # Outbox with snapshot for both
    outbox1 = EmailOutbox(
        candidate_id=cand1.id,
        kind="invitation",
        to_address=cand1.email,
        subject="Interview",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slot.id},
    )
    outbox2 = EmailOutbox(
        candidate_id=cand2.id,
        kind="invitation",
        to_address=cand2.email,
        subject="Interview",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slot.id},
    )
    main_session.add_all([outbox1, outbox2])

    msg1 = InboundMessage(candidate_id=cand1.id, from_address=cand1.email, body_text="I choose A")
    msg2 = InboundMessage(candidate_id=cand2.id, from_address=cand2.email, body_text="I choose A")
    main_session.add_all([msg1, msg2])
    main_session.commit()
    cand1_id = str(cand1.id)
    cand2_id = str(cand2.id)
    slot_id = str(slot.id)
    main_session.close()

    barrier = threading.Barrier(2)
    errors = []

    def run_worker(cand_id):
        session = SessionFactory()
        provider = FakeLLMProvider(AgentDecision(intent="choose", slot_label="A", confidence=0.95))
        try:
            barrier.wait(timeout=5)
            process_candidate_messages(session, cand_id, provider)
        except Exception as e:
            errors.append(e)
        finally:
            session.close()

    t1 = threading.Thread(target=run_worker, args=(cand1_id,))
    t2 = threading.Thread(target=run_worker, args=(cand2_id,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Errors in concurrent workers: {errors}"

    verify_session = SessionFactory()
    c1 = verify_session.get(Candidate, cand1_id)
    c2 = verify_session.get(Candidate, cand2_id)

    # Exactly one candidate is BOOKED
    statuses = {c1.status, c2.status}
    assert CandidateStatus.BOOKED in statuses
    assert len(statuses) == 2  # One booked, one not booked

    # Exactly one booking row exists
    booking_count = verify_session.query(Booking).filter_by(slot_id=slot_id).count()
    assert booking_count == 1

    # Loser candidate has slot_taken or escalation email queued
    loser_cand = c1 if c2.status == CandidateStatus.BOOKED else c2
    loser_emails = verify_session.query(EmailOutbox).filter_by(candidate_id=loser_cand.id).all()
    loser_kinds = [e.kind for e in loser_emails]
    assert "slot_taken" in loser_kinds or "escalation_ack" in loser_kinds

    verify_session.close()


def test_concurrency_same_candidate_race(tmp_path):
    engine, SessionFactory = make_file_db(tmp_path)
    main_session = SessionFactory()

    job = Job(title="Concurrency Engineer", description="Testing race conditions")
    main_session.add(job)
    interviewer = Interviewer(name="Rahul Dravid", email="rahul@example.com")
    main_session.add(interviewer)
    main_session.commit()

    cand = Candidate(job_id=job.id, name="Candidate Gamma", email="gamma@example.com", timezone="Asia/Kolkata")
    main_session.add(cand)
    main_session.commit()

    transition_candidate(main_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(main_session, cand.id, CandidateStatus.INVITED, "system")

    slot = Slot(
        job_id=job.id,
        interviewer_id=interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, minutes=30),
        status="open",
        mode="video",
    )
    main_session.add(slot)
    main_session.commit()

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Interview",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slot.id},
    )
    main_session.add(outbox)

    msg1 = InboundMessage(candidate_id=cand.id, from_address=cand.email, body_text="I choose A")
    msg2 = InboundMessage(candidate_id=cand.id, from_address=cand.email, body_text="I choose A (duplicate)")
    main_session.add_all([msg1, msg2])
    main_session.commit()
    cand_id = str(cand.id)
    slot_id = str(slot.id)
    main_session.close()

    barrier = threading.Barrier(2)
    errors = []

    def run_worker():
        session = SessionFactory()
        provider = FakeLLMProvider(AgentDecision(intent="choose", slot_label="A", confidence=0.95))
        try:
            barrier.wait(timeout=5)
            process_candidate_messages(session, cand_id, provider)
        except Exception as e:
            errors.append(e)
        finally:
            session.close()

    t1 = threading.Thread(target=run_worker)
    t2 = threading.Thread(target=run_worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Errors in concurrent workers: {errors}"

    verify_session = SessionFactory()
    c = verify_session.get(Candidate, cand_id)
    assert c.status == CandidateStatus.BOOKED

    # Exactly one booking
    booking_count = verify_session.query(Booking).filter_by(slot_id=slot_id).count()
    assert booking_count == 1

    # Exactly one confirmation email
    conf_count = verify_session.query(EmailOutbox).filter_by(candidate_id=cand.id, kind="confirmation").count()
    assert conf_count == 1

    # Both inbound messages are marked processed
    messages = verify_session.query(InboundMessage).filter_by(candidate_id=cand.id).all()
    assert all(m.processed for m in messages)

    verify_session.close()


@pytest.mark.live
def test_live_eval_dataset():
    api_key = settings.llm_api_key or os.getenv("LLM_API_KEY", "")
    if not api_key:
        pytest.skip("LLM_API_KEY not configured for live evaluation")

    from scripts.eval_llm import run_eval
    result = run_eval()
    assert result == 0
