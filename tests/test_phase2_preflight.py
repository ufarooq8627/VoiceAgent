import inspect
import pytest
from app.services.state_machine import (
    LEGAL_TRANSITIONS, CandidateStatus as S, transition_candidate, IllegalTransition,
)
from app.services.slot_service import SlotService
from app.services.email_service import EmailService


def test_transition_has_commit_flag():
    assert "commit" in inspect.signature(transition_candidate).parameters

def test_slot_book_has_commit_flag():
    assert "commit" in inspect.signature(SlotService.book).parameters

def test_enqueue_has_commit_and_offered_slots():
    params = inspect.signature(EmailService.enqueue).parameters
    assert "commit" in params and "offered_slots" in params

@pytest.mark.parametrize("pair,actor", [
    ((S.INVITED, S.BOOKED), "agent"),
    ((S.INVITED, S.FOLLOW_UP), "agent"),
    ((S.INVITED, S.DECLINED), "agent"),
    ((S.INVITED, S.NEEDS_RECRUITER), "agent"),
    ((S.FOLLOW_UP, S.BOOKED), "agent"),
    ((S.FOLLOW_UP, S.DECLINED), "agent"),
    ((S.FOLLOW_UP, S.NEEDS_RECRUITER), "agent"),
    ((S.NEEDS_RECRUITER, S.INVITED), "recruiter"),   # recruiter re-engages
    ((S.NEEDS_RECRUITER, S.BOOKED), "recruiter"),    # recruiter books manually
])
def test_required_transitions_exist(pair, actor):
    assert actor in LEGAL_TRANSITIONS.get(pair, set())

def test_transition_is_compare_and_set(db_session):
    """Stale in-memory status must not allow an illegal write."""
    from app.models import Job, Candidate
    job = Job(title="t", description="d"); db_session.add(job); db_session.commit()
    c = Candidate(job_id=job.id, name="A", email="a@x.com"); db_session.add(c); db_session.commit()
    db_session.execute(
        Candidate.__table__.update().where(Candidate.id == c.id).values(status="BOOKED"))
    db_session.commit()  # DB now BOOKED while c in memory may still say NEW
    with pytest.raises(IllegalTransition):
        transition_candidate(db_session, c.id, S.SHORTLISTED, "recruiter")
