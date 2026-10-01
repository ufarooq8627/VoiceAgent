import pytest
from app.models import Job, Candidate, CandidateEvent
from app.services.state_machine import (
    transition_candidate, IllegalTransition, CandidateStatus,
)


@pytest.fixture
def job_and_candidate(db_session):
    job = Job(title="Test", description="Test")
    db_session.add(job)
    db_session.commit()
    candidate = Candidate(job_id=job.id, name="Test User", email="test@example.com")
    db_session.add(candidate)
    db_session.commit()
    return job, candidate


def test_new_to_shortlisted(db_session, job_and_candidate):
    _, c = job_and_candidate
    result = transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    assert result.status == CandidateStatus.SHORTLISTED


def test_shortlisted_to_invited(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    result = transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    assert result.status == CandidateStatus.INVITED


def test_invited_to_booked_by_agent(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    result = transition_candidate(db_session, c.id, CandidateStatus.BOOKED, "agent")
    assert result.status == CandidateStatus.BOOKED


def test_invited_to_booked_by_candidate(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    result = transition_candidate(db_session, c.id, CandidateStatus.BOOKED, "candidate")
    assert result.status == CandidateStatus.BOOKED


def test_invited_to_follow_up(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    result = transition_candidate(db_session, c.id, CandidateStatus.FOLLOW_UP, "agent")
    assert result.status == CandidateStatus.FOLLOW_UP


def test_follow_up_to_booked(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, c.id, CandidateStatus.FOLLOW_UP, "agent")
    result = transition_candidate(db_session, c.id, CandidateStatus.BOOKED, "agent")
    assert result.status == CandidateStatus.BOOKED


def test_illegal_new_to_booked(db_session, job_and_candidate):
    _, c = job_and_candidate
    with pytest.raises(IllegalTransition):
        transition_candidate(db_session, c.id, CandidateStatus.BOOKED, "recruiter")


def test_illegal_booked_to_invited(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, c.id, CandidateStatus.BOOKED, "agent")
    with pytest.raises(IllegalTransition):
        transition_candidate(db_session, c.id, CandidateStatus.INVITED, "system")


def test_transition_creates_event(db_session, job_and_candidate):
    _, c = job_and_candidate
    transition_candidate(db_session, c.id, CandidateStatus.SHORTLISTED, "recruiter", {"reason": "good fit"})
    events = db_session.query(CandidateEvent).filter_by(candidate_id=c.id).all()
    assert len(events) == 1
    assert events[0].event_type == "shortlisted"
    assert events[0].actor == "recruiter"
    assert events[0].payload == {"reason": "good fit"}


def test_candidate_not_found(db_session):
    with pytest.raises(ValueError, match="not found"):
        transition_candidate(db_session, "nonexistent-id", CandidateStatus.SHORTLISTED, "recruiter")
