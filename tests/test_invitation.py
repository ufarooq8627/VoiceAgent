import hashlib
import pytest
from app.models import Job, Candidate, Invitation, EmailOutbox, Slot, Interviewer
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.invitation_service import InvitationService
from app.services.email_service import EmailService
from app.services.slot_service import SlotService
from app.providers.email_provider import MockEmailProvider


@pytest.fixture
def setup_data(db_session):
    job = Job(title="Python Engineer", description="FastAPI")
    db_session.add(job)
    interviewer = Interviewer(name="Rahul V", email="rahul@example.com")
    db_session.add(interviewer)
    db_session.commit()

    candidate = Candidate(job_id=job.id, name="Sneha Rao", email="sneha@example.com")
    db_session.add(candidate)
    db_session.commit()
    transition_candidate(db_session, candidate.id, CandidateStatus.SHORTLISTED, "recruiter")

    return job, candidate, interviewer


def test_create_invitation_returns_token(db_session, setup_data):
    _, candidate, _ = setup_data
    invitation, raw_token = InvitationService.create_invitation(db_session, candidate.id)
    assert invitation.id is not None
    assert invitation.candidate_id == candidate.id
    assert raw_token is not None
    assert len(raw_token) > 20


def test_token_hash_stored_not_raw(db_session, setup_data):
    _, candidate, _ = setup_data
    invitation, raw_token = InvitationService.create_invitation(db_session, candidate.id)
    # The database must NEVER store the raw token
    assert raw_token not in invitation.token_hash
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    assert invitation.token_hash == expected_hash


def test_validate_valid_token(db_session, setup_data):
    _, candidate, _ = setup_data
    invitation, raw_token = InvitationService.create_invitation(db_session, candidate.id)
    validated = InvitationService.validate_token(db_session, raw_token)
    assert validated is not None
    assert validated.id == invitation.id


def test_validate_invalid_token(db_session, setup_data):
    validated = InvitationService.validate_token(db_session, "nonexistent-token-xyz")
    assert validated is None


def test_validate_empty_token(db_session, setup_data):
    assert InvitationService.validate_token(db_session, "") is None
    assert InvitationService.validate_token(db_session, "   ") is None


def test_email_enqueue_and_drain(db_session, setup_data):
    job, candidate, interviewer = setup_data
    provider = MockEmailProvider()

    outbox = EmailService.enqueue(
        db=db_session,
        candidate_id=candidate.id,
        kind="test",
        to_address=candidate.email,
        subject="Test Subject",
        body_html="<p>Test</p>",
        body_text="Test",
    )
    assert outbox.status == "queued"

    sent_count = EmailService.drain_outbox(db_session, batch_size=10, provider=provider)
    assert sent_count == 1
    db_session.refresh(outbox)
    assert outbox.status == "sent"
    assert outbox.sent_at is not None
    assert len(provider.sent_emails) == 1
    assert provider.sent_emails[0]["to"] == candidate.email
