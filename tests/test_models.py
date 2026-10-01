from sqlalchemy import inspect
from app.models import Job, Candidate


def test_all_tables_created(db_session):
    inspector = inspect(db_session.bind)
    tables = inspector.get_table_names()
    expected = [
        "jobs",
        "candidates",
        "interviewers",
        "slots",
        "invitations",
        "bookings",
        "email_outbox",
        "inbound_messages",
        "conversation_messages",
        "candidate_events",
    ]
    for table in expected:
        assert table in tables, f"Table '{table}' not found"


def test_create_job(db_session):
    job = Job(title="Backend Developer", description="Python + FastAPI")
    db_session.add(job)
    db_session.commit()
    assert job.id is not None
    assert job.status == "draft"


def test_create_candidate_with_job(db_session):
    job = Job(title="Test Job", description="Test")
    db_session.add(job)
    db_session.commit()
    candidate = Candidate(job_id=job.id, name="Rahul Sharma", email="rahul@example.com")
    db_session.add(candidate)
    db_session.commit()
    assert candidate.status == "NEW"
    assert candidate.timezone == "Asia/Kolkata"
