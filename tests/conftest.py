from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Job, Interviewer, Candidate, Slot, EmailOutbox, InboundMessage, Invitation
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def invited_candidate(db_session):
    job = Job(title="Senior Cloud Architect", description="Cloud architecture")
    db_session.add(job)
    interviewer = Interviewer(name="Vikram Seth", email="vikram@example.com")
    db_session.add(interviewer)
    db_session.commit()

    cand = Candidate(
        job_id=job.id,
        name="Sunil Gavaskar",
        email="sunil@example.com",
        timezone="Asia/Kolkata",
    )
    db_session.add(cand)
    db_session.commit()
    transition_candidate(db_session, cand.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand.id, CandidateStatus.INVITED, "system")

    slots = SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, hours=1, minutes=30),
        duration_minutes=30,
    )
    db_session.commit()

    inv = Invitation(candidate_id=cand.id, token_hash="dummy-hash-456", outcome="pending")
    db_session.add(inv)

    outbox = EmailOutbox(
        candidate_id=cand.id,
        kind="invitation",
        to_address=cand.email,
        subject="Interview Invitation: Senior Cloud Architect",
        body_html="<p>Invite</p>",
        body_text="Invite",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[0].id, "B": slots[1].id, "C": slots[2].id},
    )
    db_session.add(outbox)
    db_session.commit()

    def create_inbound(body_text: str, headers: dict | None = None, subject: str = "Re: Interview Invitation") -> InboundMessage:
        msg = InboundMessage(
            candidate_id=cand.id,
            from_address=cand.email,
            subject=subject,
            body_text=body_text,
            raw_headers=headers,
            processed=False,
        )
        db_session.add(msg)
        db_session.commit()
        db_session.refresh(msg)
        return msg

    return job, cand, slots, create_inbound

from app.limiter import limiter
limiter.enabled = False
