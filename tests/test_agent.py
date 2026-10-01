import pytest
from pydantic import ValidationError
from app.models import Job, Candidate, Interviewer, InboundMessage, CandidateEvent
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.schemas.agent import AgentDecision
from app.agent.tools import AgentTools
from app.services.agent_service import AgentService


@pytest.fixture
def agent_setup(db_session):
    job = Job(title="Lead Architect", description="Architecture")
    db_session.add(job)
    interviewer = Interviewer(name="Kavita S", email="kavita@example.com")
    db_session.add(interviewer)
    db_session.commit()

    candidate = Candidate(job_id=job.id, name="Deepak Verma", email="deepak@example.com")
    db_session.add(candidate)
    db_session.commit()
    transition_candidate(db_session, candidate.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, candidate.id, CandidateStatus.INVITED, "system")

    from datetime import datetime, timezone
    SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc),
        end_at_utc=datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc),
        duration_minutes=30,
    )

    return job, candidate, interviewer


def test_agent_decision_validation():
    # Valid choose
    d1 = AgentDecision(intent="choose", slot_label="A", confidence=0.95)
    assert d1.slot_label == "A"

    # Missing slot_label for choose must raise ValidationError
    with pytest.raises(ValidationError):
        AgentDecision(intent="choose", confidence=0.95)

    # Valid decline
    d2 = AgentDecision(intent="decline", decline_reason="accepted another offer", confidence=0.9)
    assert d2.intent == "decline"


def test_agent_tools_booking_and_context(db_session, agent_setup):
    job, candidate, _ = agent_setup
    tools = AgentTools(db=db_session, candidate_id=candidate.id)

    ctx = tools.get_candidate_context()
    assert ctx["name"] == candidate.name
    assert ctx["status"] == CandidateStatus.INVITED

    slots = tools.get_open_slots()
    assert len(slots) == 2
    assert slots[0]["label"] == "A"

    # Book slot A
    res = tools.book_slot("A")
    assert res["success"] is True

    db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.BOOKED

    # Slot A is now booked, remaining slots should be 1
    rem = tools.get_open_slots()
    assert len(rem) == 1
    assert rem[0]["label"] == "A"  # re-indexed as slot A


def test_agent_tools_escalate_and_decline(db_session, agent_setup):
    job, candidate, _ = agent_setup
    tools = AgentTools(db=db_session, candidate_id=candidate.id)

    tools.escalate_to_recruiter("Times do not suit candidate")
    db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.NEEDS_RECRUITER


def test_agent_service_process_reply_stub(db_session, agent_setup):
    job, candidate, _ = agent_setup
    inbound = InboundMessage(
        candidate_id=candidate.id,
        from_address=candidate.email,
        subject="Re: Invitation",
        body_text="I prefer slot B please",
        processed=False,
    )
    db_session.add(inbound)
    db_session.commit()

    AgentService.process_reply(db_session, inbound.id)
    db_session.refresh(inbound)
    assert inbound.processed is True

    events = db_session.query(CandidateEvent).filter_by(candidate_id=candidate.id).all()
    assert any(e.event_type == "reply_received" for e in events)
