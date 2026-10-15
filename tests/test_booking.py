from datetime import datetime, timedelta, timezone
import pytest
from app.models import Job, Interviewer, Slot, Candidate, Booking
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService


# Use a future base date so slots remain "open" regardless of when tests run
def _future_dt(days_ahead=7, hour=10, minute=0):
    base = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture
def setup_job_and_interviewer(db_session):
    job = Job(title="Backend Engineer", description="Python/FastAPI")
    db_session.add(job)
    interviewer = Interviewer(name="Priya Patel", email="priya@example.com")
    db_session.add(interviewer)
    db_session.commit()
    return job, interviewer


@pytest.fixture
def candidate_invited(db_session, setup_job_and_interviewer):
    job, _ = setup_job_and_interviewer
    candidate = Candidate(job_id=job.id, name="Vikas Kumar", email="vikas@example.com")
    db_session.add(candidate)
    db_session.commit()
    transition_candidate(db_session, candidate.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, candidate.id, CandidateStatus.INVITED, "system")
    return candidate


def test_create_slots_from_window(db_session, setup_job_and_interviewer):
    job, interviewer = setup_job_and_interviewer
    start = _future_dt(days_ahead=7, hour=10)
    end = _future_dt(days_ahead=7, hour=12)
    slots = SlotService.create_slots(
        db=db_session,
        job_id=job.id,
        interviewer_id=interviewer.id,
        start_at_utc=start,
        end_at_utc=end,
        duration_minutes=30,
    )
    assert len(slots) == 4
    # SQLite returns naive datetime in UTC
    assert slots[0].start_at_utc.replace(tzinfo=timezone.utc) == start
    assert slots[0].status == "open"


def test_book_slot_atomically(db_session, setup_job_and_interviewer, candidate_invited):
    job, interviewer = setup_job_and_interviewer
    candidate = candidate_invited
    start = _future_dt(days_ahead=8, hour=14)
    end = _future_dt(days_ahead=8, hour=14, minute=30)
    slots = SlotService.create_slots(
        db_session, job.id, interviewer.id, start, end, duration_minutes=30
    )
    slot = slots[0]

    success, result = SlotService.book(db_session, slot.id, candidate.id, actor="agent")
    assert success is True
    assert isinstance(result, Booking)
    assert result.slot_id == slot.id
    assert result.candidate_id == candidate.id

    db_session.refresh(slot)
    assert slot.status == "booked"

    db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.BOOKED


def test_double_booking_prevented(db_session, setup_job_and_interviewer, candidate_invited):
    job, interviewer = setup_job_and_interviewer
    c1 = candidate_invited
    c2 = Candidate(job_id=job.id, name="Second Candidate", email="second@example.com")
    db_session.add(c2)
    db_session.commit()
    transition_candidate(db_session, c2.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c2.id, CandidateStatus.INVITED, "system")

    start = _future_dt(days_ahead=9, hour=15)
    end = _future_dt(days_ahead=9, hour=15, minute=30)
    slots = SlotService.create_slots(
        db_session, job.id, interviewer.id, start, end, duration_minutes=30
    )
    slot = slots[0]

    # First booking succeeds
    success1, result1 = SlotService.book(db_session, slot.id, c1.id, actor="agent")
    assert success1 is True

    # Second booking must fail atomically
    success2, result2 = SlotService.book(db_session, slot.id, c2.id, actor="agent")
    assert success2 is False
    assert "not available" in str(result2).lower() or "already booked" in str(result2).lower()


def test_get_available_returns_only_open(db_session, setup_job_and_interviewer, candidate_invited):
    job, interviewer = setup_job_and_interviewer
    start = _future_dt(days_ahead=10, hour=10)
    end = _future_dt(days_ahead=10, hour=11, minute=30)
    slots = SlotService.create_slots(
        db_session, job.id, interviewer.id, start, end, duration_minutes=30
    )
    assert len(slots) == 3

    # Book slot 0
    SlotService.book(db_session, slots[0].id, candidate_invited.id, actor="agent")

    available = SlotService.get_available(db_session, job.id)
    assert len(available) == 2
    assert available[0]["label"] == "A"
    assert available[1]["label"] == "B"
    assert available[0]["id"] == slots[1].id
    assert available[1]["id"] == slots[2].id


def test_cancel_slot(db_session, setup_job_and_interviewer):
    job, interviewer = setup_job_and_interviewer
    start = _future_dt(days_ahead=11, hour=10)
    end = _future_dt(days_ahead=11, hour=10, minute=30)
    slots = SlotService.create_slots(
        db_session, job.id, interviewer.id, start, end, duration_minutes=30
    )
    slot = slots[0]

    cancelled = SlotService.cancel(db_session, slot.id)
    assert cancelled is True
    db_session.refresh(slot)
    assert slot.status == "cancelled"