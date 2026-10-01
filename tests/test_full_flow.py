from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Job, Candidate, Interviewer, Slot, Invitation, InboundMessage, EmailOutbox
from app.services.state_machine import CandidateStatus
from app.services.invitation_service import InvitationService

# Isolated in-memory SQLite engine for integration tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_client():
    client = TestClient(app)
    # Log in as admin
    res = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    return client


def test_security_unauthenticated_blocked():
    client = TestClient(app)
    res = client.get("/admin/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/login"

    res2 = client.get("/admin/mock-inbox", follow_redirects=False)
    assert res2.status_code == 303
    assert res2.headers["location"] == "/admin/login"


def test_full_recruitment_workflow(auth_client, db):
    # 1. Create a Job Campaign
    res = auth_client.post(
        "/admin/jobs",
        data={"title": "Staff Platform Engineer", "description": "K8s + Go + Python"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    job_url = res.headers["location"]
    job_id = job_url.split("/")[-1]

    # Verify job created in DB
    job = db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.title == "Staff Platform Engineer"

    # 2. Add an Interviewer
    res = auth_client.post(
        "/admin/interviewers",
        data={"name": "Siddharth Verma", "email": "siddharth@example.com"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    interviewer = db.query(Interviewer).filter(Interviewer.email == "siddharth@example.com").first()
    assert interviewer is not None

    # 3. Add Time Slots for Job
    res = auth_client.post(
        f"/admin/jobs/{job_id}/slots",
        data={
            "interviewer_id": interviewer.id,
            "start_at": "2026-10-15T10:00",
            "end_at": "2026-10-15T12:00",
            "duration_minutes": "30",
            "mode": "video",
            "location_or_link": "https://meet.google.com/test-room",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    slots = db.query(Slot).filter(Slot.job_id == job_id).all()
    assert len(slots) == 4

    # 4. Generate 20 Mock Candidates
    res = auth_client.post(
        f"/admin/jobs/{job_id}/generate-candidates",
        follow_redirects=False,
    )
    assert res.status_code == 303
    candidates = db.query(Candidate).filter(Candidate.job_id == job_id).all()
    assert len(candidates) == 20

    # 5. Shortlist Candidates
    c1, c2 = candidates[0], candidates[1]
    res = auth_client.post(
        f"/admin/candidates/{c1.id}/shortlist",
        data={"job_id": job_id},
        follow_redirects=False,
    )
    assert res.status_code == 303
    db.refresh(c1)
    assert c1.status == CandidateStatus.SHORTLISTED

    # Bulk shortlist c2
    res = auth_client.post(
        "/admin/candidates/bulk-shortlist",
        data={"job_id": job_id, "candidate_ids": [c2.id]},
        follow_redirects=False,
    )
    assert res.status_code == 303
    db.refresh(c2)
    assert c2.status == CandidateStatus.SHORTLISTED

    # 6. Send Batch Email Invitations
    res = auth_client.post(
        f"/admin/jobs/{job_id}/send-invitations",
        follow_redirects=False,
    )
    assert res.status_code == 303
    db.refresh(c1)
    db.refresh(c2)
    assert c1.status == CandidateStatus.INVITED
    assert c2.status == CandidateStatus.INVITED

    # Verify invitations and outbox
    inv1 = db.query(Invitation).filter(Invitation.candidate_id == c1.id).first()
    assert inv1 is not None
    assert inv1.outcome == "pending"

    # Outbox message should exist
    outbox_msgs = db.query(EmailOutbox).filter(EmailOutbox.candidate_id == c1.id).all()
    assert len(outbox_msgs) >= 1

    # 7. Fallback Token Booking Flow (Candidate c1 books via web)
    _, raw_token = InvitationService.create_invitation(db, c1.id)

    public_client = TestClient(app)
    # GET public booking page
    book_page_res = public_client.get(f"/i/{raw_token}")
    assert book_page_res.status_code == 200
    assert c1.name in book_page_res.text

    # POST book slot
    slot_to_book = slots[0]
    book_action_res = public_client.post(
        f"/i/{raw_token}/book",
        data={"slot_id": slot_to_book.id},
    )
    assert book_action_res.status_code == 200
    assert "Interview Confirmed!" in book_action_res.text

    db.refresh(c1)
    assert c1.status == CandidateStatus.BOOKED

    # Try booking same slot again with c2 -> must fail
    _, raw_token_c2 = InvitationService.create_invitation(db, c2.id)
    double_book_res = public_client.post(
        f"/i/{raw_token_c2}/book",
        data={"slot_id": slot_to_book.id},
    )
    assert double_book_res.status_code == 400
    assert "Booking failed" in double_book_res.text

    # c2 declines instead
    decline_res = public_client.post(f"/i/{raw_token_c2}/decline")
    assert decline_res.status_code == 200
    assert "Interview Declined" in decline_res.text
    db.refresh(c2)
    assert c2.status == CandidateStatus.DECLINED

    # 8. Simulate Candidate Reply in Mock Inbox
    inbox_res = auth_client.post(
        "/admin/mock-inbox/simulate",
        data={
            "candidate_id": c1.id,
            "from_address": c1.email,
            "subject": "Re: Thanks for confirming",
            "body_text": "Looking forward to speaking with the team!",
        },
        follow_redirects=False,
    )
    assert inbox_res.status_code == 303
    msg = db.query(InboundMessage).filter(InboundMessage.candidate_id == c1.id).first()
    assert msg is not None
    assert "Looking forward" in msg.body_text

    # 9. Verify Conversation History Page
    history_res = auth_client.get(f"/admin/candidates/{c1.id}/conversations")
    assert history_res.status_code == 200
    assert c1.name in history_res.text

    # 10. Excel Export Download
    export_res = auth_client.get(f"/admin/jobs/{job_id}/export")
    assert export_res.status_code == 200
    assert export_res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(export_res.content) > 1000

    # 11. API Ingestion Test
    api_client = TestClient(app)
    api_res = api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={
            "name": "Arjun Kapoor",
            "email": "arjun.k@example.com",
            "phone": "+919876500000",
            "skills": ["Go", "Kubernetes", "Python"],
            "experience_years": 7,
            "current_company": "CloudNative Labs",
            "designation": "Senior DevOps Engineer",
            "expected_salary": "₹28 LPA",
        },
    )
    assert api_res.status_code == 201
    data = api_res.json()
    assert data["name"] == "Arjun Kapoor"
    assert data["source"] == "api"
    assert data["status"] == "NEW"
