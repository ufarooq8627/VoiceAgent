import pytest
from app.models import Job
from app.schemas.candidate import CandidateCreate
from app.services.candidate_service import CandidateService


@pytest.fixture
def job(db_session):
    job = Job(title="Senior Backend Developer", description="Python + FastAPI role")
    db_session.add(job)
    db_session.commit()
    return job


def test_generate_mock_creates_20(db_session, job):
    candidates = CandidateService.generate_mock(db_session, job.id, count=20)
    assert len(candidates) == 20


def test_mock_candidates_have_required_fields(db_session, job):
    candidates = CandidateService.generate_mock(db_session, job.id, count=5)
    for c in candidates:
        assert c.name and c.email and "@" in c.email
        assert c.skills is not None and 4 <= len(c.skills) <= 8
        assert 1 <= c.experience_years <= 15
        assert c.source == "mock" and c.status == "NEW"


def test_mock_skills_match_backend_job(db_session, job):
    candidates = CandidateService.generate_mock(db_session, job.id, count=10)
    backend_skills = {"Python", "FastAPI", "Django", "PostgreSQL", "Redis", "Node.js"}
    for c in candidates:
        assert any(s in backend_skills for s in c.skills)


def test_get_by_job_paginated(db_session, job):
    CandidateService.generate_mock(db_session, job.id, count=20)
    page1 = CandidateService.get_by_job(db_session, job.id, page=1, per_page=10)
    page2 = CandidateService.get_by_job(db_session, job.id, page=2, per_page=10)
    assert len(page1) == 10 and len(page2) == 10
    assert {c.id for c in page1}.isdisjoint({c.id for c in page2})


def test_get_by_job_status_filter(db_session, job):
    CandidateService.generate_mock(db_session, job.id, count=5)
    assert len(CandidateService.get_by_job(db_session, job.id, status_filter="NEW")) == 5
    assert len(CandidateService.get_by_job(db_session, job.id, status_filter="SHORTLISTED")) == 0


def test_create_from_api(db_session, job):
    payload = CandidateCreate(
        name="Aarav Mehta",
        email="aarav@example.com",
        phone="+919876543210",
        skills=["Python", "FastAPI"],
        experience_years=4,
        current_company="TechCorp",
        designation="Software Engineer",
        expected_salary="₹15 LPA",
    )
    candidate = CandidateService.create_from_api(db_session, job.id, payload)
    assert candidate.id is not None
    assert candidate.source == "api"
    assert candidate.status == "NEW"
    assert candidate.name == "Aarav Mehta"
