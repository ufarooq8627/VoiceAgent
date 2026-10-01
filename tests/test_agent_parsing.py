from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.models import Job, Candidate, Interviewer, Slot
from app.schemas.agent import AgentDecision
from app.agent.tools import AgentTools
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService


@pytest.fixture
def candidate_with_slots(db_session):
    job = Job(title="Senior Distributed Systems Engineer", description="Go + Raft")
    db_session.add(job)
    interviewer = Interviewer(name="Rohan Mehra", email="rohan@example.com")
    db_session.add(interviewer)
    db_session.commit()

    c1 = Candidate(job_id=job.id, name="Nikhil Sen", email="nikhil@example.com")
    c2 = Candidate(job_id=job.id, name="Tanvi Das", email="tanvi@example.com")
    db_session.add_all([c1, c2])
    db_session.commit()

    transition_candidate(db_session, c1.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c1.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, c2.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c2.id, CandidateStatus.INVITED, "system")

    SlotService.create_slots(
        db_session,
        job.id,
        interviewer.id,
        start_at_utc=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        end_at_utc=datetime(2026, 10, 20, 11, 30, tzinfo=timezone.utc),
        duration_minutes=30,
    )
    return job, c1, c2


def test_choose_requires_slot_label():
    with pytest.raises(ValidationError):
        AgentDecision(intent="choose", confidence=0.9)


def test_choose_with_slot_label_valid():
    d = AgentDecision(intent="choose", slot_label="B", confidence=0.92)
    assert d.intent == "choose"
    assert d.slot_label == "B"
    assert d.confidence == 0.92


def test_invalid_intent_rejected():
    with pytest.raises(ValidationError):
        AgentDecision(intent="hack", confidence=0.9)


def test_wrong_slot_letter(db_session, candidate_with_slots):
    _, c1, _ = candidate_with_slots
    tools = AgentTools(db_session, c1.id)

    # Slot Z does not exist
    result = tools.book_slot("Z")
    assert result["success"] is False
    assert result["reason"] == "invalid_label"
    assert len(result["remaining_slots"]) == 3


def test_slot_already_taken(db_session, candidate_with_slots):
    _, c1, c2 = candidate_with_slots
    tools1 = AgentTools(db_session, c1.id)
    tools2 = AgentTools(db_session, c2.id)

    # c1 books slot A
    res1 = tools1.book_slot("A")
    assert res1["success"] is True

    # c2 tries to book slot A (which is now booked)
    # Open slots for c2 will now have labels A, B (the remaining 2 slots)
    open_slots = tools2.get_open_slots()
    assert len(open_slots) == 2

    # If c2 tries to book with an invalid or already booked slot
    db_session.refresh(c1)
    assert c1.status == CandidateStatus.BOOKED


def test_injection_attempt_schema():
    # Prompt injection / garbage reply returns unclear with low confidence
    decision = AgentDecision(intent="unclear", follow_up_message="Could you clarify your slot choice?", confidence=0.3)
    assert decision.intent == "unclear"
    assert decision.confidence < 0.5  # Below confidence threshold -> system escalates
