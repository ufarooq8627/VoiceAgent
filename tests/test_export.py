from datetime import datetime, timezone
import pytest
from app.models import Job, Candidate, Interviewer, Slot, Booking, ConversationMessage
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.export_service import ExportService


@pytest.fixture
def populated_job(db_session):
    job = Job(title="Senior ML Engineer", description="PyTorch / LLMs")
    db_session.add(job)
    interviewer = Interviewer(name="Dr. Anil Gupta", email="anil@example.com")
    db_session.add(interviewer)
    db_session.commit()

    # Candidate 1: Booked
    c1 = Candidate(job_id=job.id, name="Aditi Rao", email="aditi@example.com")
    db_session.add(c1)
    db_session.commit()
    transition_candidate(db_session, c1.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c1.id, CandidateStatus.INVITED, "system")

    slot = Slot(
        job_id=job.id,
        interviewer_id=interviewer.id,
        start_at_utc=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
        end_at_utc=datetime(2026, 10, 10, 10, 30, tzinfo=timezone.utc),
        mode="video",
        location_or_link="https://meet.google.com/abc-xyz",
        status="booked",
    )
    db_session.add(slot)
    db_session.commit()

    booking = Booking(candidate_id=c1.id, slot_id=slot.id, status="confirmed")
    db_session.add(booking)
    transition_candidate(db_session, c1.id, CandidateStatus.BOOKED, "agent")

    # Candidate 2: Declined
    c2 = Candidate(job_id=job.id, name="Suresh Nair", email="suresh@example.com")
    db_session.add(c2)
    db_session.commit()
    transition_candidate(db_session, c2.id, CandidateStatus.SHORTLISTED, "recruiter")
    transition_candidate(db_session, c2.id, CandidateStatus.INVITED, "system")
    transition_candidate(db_session, c2.id, CandidateStatus.DECLINED, "agent", {"reason": "Not interested"})

    # Conversation message for c1
    msg = ConversationMessage(
        candidate_id=c1.id,
        direction="outbound",
        summary="Sent invitation with 5 slots",
    )
    db_session.add(msg)
    db_session.commit()

    return job, c1, c2, booking


def test_export_has_three_sheets(db_session, populated_job):
    job, _, _, _ = populated_job
    wb = ExportService.export_job(db_session, job.id)
    assert wb.sheetnames == ["Schedule", "Not Scheduled", "Conversation Log"]


def test_export_schedule_sheet(db_session, populated_job):
    job, c1, _, booking = populated_job
    wb = ExportService.export_job(db_session, job.id)
    sheet = wb["Schedule"]

    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("Date", "Time", "Interviewer", "Candidate", "Email", "Mode", "Link")
    assert len(rows) == 2  # 1 header + 1 booking
    assert rows[1][3] == c1.name
    assert rows[1][4] == c1.email
    assert rows[1][2] == "Dr. Anil Gupta"


def test_export_not_scheduled_sheet(db_session, populated_job):
    job, _, c2, _ = populated_job
    wb = ExportService.export_job(db_session, job.id)
    sheet = wb["Not Scheduled"]

    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("Name", "Email", "Status", "Reason")
    assert len(rows) == 2  # 1 header + 1 candidate
    assert rows[1][0] == c2.name
    assert rows[1][2] == "DECLINED"


def test_export_conversation_log_sheet(db_session, populated_job):
    job, c1, _, _ = populated_job
    wb = ExportService.export_job(db_session, job.id)
    sheet = wb["Conversation Log"]

    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("Candidate", "Direction", "Summary", "Timestamp")
    assert len(rows) == 2
    assert rows[1][0] == c1.name
    assert rows[1][1] == "outbound"
