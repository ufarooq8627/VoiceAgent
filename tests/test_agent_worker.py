from datetime import datetime, timezone, timedelta
import pytest
from app.models import Job, Candidate, Interviewer, Slot, EmailOutbox, InboundMessage
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.schemas.agent import AgentDecision
from app.agent.worker import agent_tick, scheduler, start_scheduler
from tests.fakes import FakeLLMProvider


@pytest.fixture
def worker_setup(db_session):
    job = Job(title="DevOps Lead", description="Kubernetes")
    db_session.add(job)
    interviewer = Interviewer(name="Karan", email="karan@example.com")
    db_session.add(interviewer)
    db_session.commit()

    cand1 = Candidate(job_id=job.id, name="Candidate One", email="c1@example.com")
    cand2 = Candidate(job_id=job.id, name="Candidate Two", email="c2@example.com")
    db_session.add_all([cand1, cand2])
    db_session.commit()

    transition_candidate(db_session, cand1.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand1.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, cand2.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, cand2.id, CandidateStatus.INVITED, "system")

    slots = SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        end_at_utc=datetime.now(timezone.utc) + timedelta(days=2, hours=2),
        duration_minutes=30,
    )
    db_session.commit()

    out1 = EmailOutbox(
        candidate_id=cand1.id,
        kind="invitation",
        to_address=cand1.email,
        subject="Invite",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[0].id, "B": slots[1].id},
    )
    out2 = EmailOutbox(
        candidate_id=cand2.id,
        kind="invitation",
        to_address=cand2.email,
        subject="Invite",
        body_html="<p>i</p>",
        body_text="i",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        offered_slots={"A": slots[2].id, "B": slots[3].id},
    )
    db_session.add_all([out1, out2])
    db_session.commit()

    return job, cand1, cand2, slots


def test_tick_processes_then_drains(db_session, worker_setup):
    job, cand1, _, slots = worker_setup
    msg = InboundMessage(
        candidate_id=cand1.id,
        from_address=cand1.email,
        subject="Re: Invite",
        body_text="Slot A please",
        processed=False,
    )
    db_session.add(msg)
    db_session.commit()

    provider = FakeLLMProvider(AgentDecision(intent="choose", slot_label="A", confidence=0.95))

    # Run agent_tick with session factory returning db_session
    class TestSessionFactory:
        def __call__(self):
            return self
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    agent_tick(session_factory=TestSessionFactory(), provider=provider)

    db_session.refresh(msg)
    assert msg.processed is True

    db_session.refresh(cand1)
    assert cand1.status == CandidateStatus.BOOKED

    conf_mail = db_session.query(EmailOutbox).filter_by(candidate_id=cand1.id, kind="confirmation").first()
    assert conf_mail is not None
    assert conf_mail.status == "sent"


def test_tick_isolates_failures(db_session, worker_setup):
    job, cand1, cand2, slots = worker_setup
    msg1 = InboundMessage(candidate_id=cand1.id, from_address=cand1.email, subject="Re:", body_text="Slot A", processed=False)
    msg2 = InboundMessage(candidate_id=cand2.id, from_address=cand2.email, subject="Re:", body_text="Slot A", processed=False)
    db_session.add_all([msg1, msg2])
    db_session.commit()

    class FailingThenPassingProvider:
        def classify(self, text, ctx):
            if "Candidate One" in ctx.get("name", ""):
                raise RuntimeError("Unexpected boom!")
            return AgentDecision(intent="choose", slot_label="A", confidence=0.95)

    class TestSessionFactory:
        def __call__(self):
            return self
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    agent_tick(session_factory=TestSessionFactory(), provider=FailingThenPassingProvider())

    db_session.refresh(cand2)
    assert cand2.status == CandidateStatus.BOOKED

    db_session.refresh(msg2)
    assert msg2.processed is True


def test_scheduler_job_options():
    start_scheduler()
    job = scheduler.get_job("agent_tick") or scheduler.get_job("agent_tick_job")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True


def test_noop_provider_escalates(db_session, worker_setup):
    job, cand1, _, _ = worker_setup
    msg = InboundMessage(candidate_id=cand1.id, from_address=cand1.email, subject="Re:", body_text="Slot A", processed=False)
    db_session.add(msg)
    db_session.commit()

    from app.providers.llm_provider import NoOpLLMProvider

    class TestSessionFactory:
        def __call__(self):
            return self
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    agent_tick(session_factory=TestSessionFactory(), provider=NoOpLLMProvider())

    db_session.refresh(cand1)
    db_session.refresh(msg)
    assert cand1.status == CandidateStatus.NEEDS_RECRUITER
    assert msg.processed is True
