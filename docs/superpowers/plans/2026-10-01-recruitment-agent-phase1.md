# Recruitment Agent — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 recruitment agent: jobs, candidates, interviewers, slots, email outbox (mock), mock inbox page, admin dashboard (Jinja2 + HTMX), fallback token booking page, Excel export, and all wiring for the Phase 2 agent loop.

**Architecture:** FastAPI + SQLAlchemy + SQLite backend. Jinja2 + HTMX server-rendered admin panel. APScheduler for the agent worker (outbox drain in Phase 1). Mock email provider. Token-based fallback booking page. The state machine is the single status writer for all candidate transitions.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic 2.0, Jinja2, HTMX, APScheduler, Faker, openpyxl, bcrypt, slowapi, SQLite

**Spec:** [2026-10-01-recruitment-agent-design.md](file:///C:/Users/FAROOQUE/.gemini/antigravity-ide/scratch/recruitment-agent/docs/superpowers/specs/2026-10-01-recruitment-agent-design.md)

## Global Constraints

- Python 3.11+ required (for `str | None` union syntax)
- All timestamps stored as UTC `datetime` in SQLAlchemy. No naive datetimes.
- UUIDs as primary keys on all tables (use `uuid.uuid4`)
- No business logic in route handlers — services only
- `candidate.status` is written ONLY by `transition_candidate()` in `state_machine.py`
- LLM is not called in Phase 1. `agent_service.process_reply()` is a stub.
- All email sending goes through the outbox. No direct sends.
- Project root: `C:\Users\FAROOQUE\.gemini\antigravity-ide\scratch\recruitment-agent`

## Review Focus

1. **Concurrent booking of the same slot** — Two requests arrive simultaneously for the same open slot. Exactly one must succeed, the other must get a clear "slot taken" error. The atomic UPDATE + row count check is the only protection; application-level locks are not used.
2. **Illegal state transitions** — A route or service accidentally calling `candidate.status = "BOOKED"` directly instead of going through `transition_candidate()`. Any bypass must raise an error or be caught in review.
3. **Token leakage** — The raw invitation token must never appear in the database, logs, or error messages. Only the SHA-256 hash is stored. The raw token exists only in the email body and the URL.
4. **HTMX partial vs full page** — Admin GET routes must return a full HTML page on normal requests and an HTML fragment when `HX-Request` header is present. Returning a full page inside an HTMX swap breaks the UI.
5. **Mock inbox auth gate** — The mock inbox page must be behind both `MOCK_INBOX=true` config check AND admin session auth. Exposing it without auth in any environment is a security issue.

---

### Task 1: Project Foundation — Config, Database, Models

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/database.py`
- Create: `app/models/__init__.py`
- Create: `app/models/job.py`
- Create: `app/models/candidate.py`
- Create: `app/models/interviewer.py`
- Create: `app/models/slot.py`
- Create: `app/models/invitation.py`
- Create: `app/models/booking.py`
- Create: `app/models/email_outbox.py`
- Create: `app/models/inbound_message.py`
- Create: `app/models/conversation_message.py`
- Create: `app/models/candidate_event.py`
- Create: `app/main.py` (skeleton)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Base` (SQLAlchemy declarative base), `get_db()` session dependency, `Settings` config class, all 10 model classes importable from `app.models`

- [ ] **Step 1: Create requirements.txt**

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-multipart>=0.0.6
jinja2>=3.1.0
itsdangerous>=2.1.0
bcrypt>=4.0.0
faker>=20.0.0
openpyxl>=3.1.0
apscheduler>=3.10.0
slowapi>=0.1.9
python-dotenv>=1.0.0
aiofiles>=23.0.0
httpx>=0.25.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

- [ ] **Step 2: Create .env.example**

```env
APP_SECRET_KEY=change-me-to-random-64-chars
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=$2b$12$LJ3m4ys3Lz0QhRdQj4b0cOQaLmR4hHnKJ7VzVhOdN3dCzKgPcXmO6
DATABASE_URL=sqlite:///./recruitment.db
EMAIL_PROVIDER=mock
MOCK_INBOX=true
AGENT_TICK_INTERVAL_SECONDS=30
OUTBOX_BATCH_SIZE=50
LLM_PROVIDER=none
LLM_API_KEY=
LLM_MODEL=
AGENT_CONFIDENCE_THRESHOLD=0.5
```

- [ ] **Step 3: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 4: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password_hash: str = ""
    database_url: str = "sqlite:///./recruitment.db"
    email_provider: str = "mock"
    mock_inbox: bool = True
    agent_tick_interval_seconds: int = 30
    outbox_batch_size: int = 50
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    agent_confidence_threshold: float = 0.5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 5: Create app/database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 6: Create all model files**

Create `app/models/job.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    candidates = relationship("Candidate", back_populates="job")
    slots = relationship("Slot", back_populates="job")
```

Create `app/models/candidate.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expected_salary: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resume_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="mock")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(30), default="NEW", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="candidates")
    bookings = relationship("Booking", back_populates="candidate")
    invitations = relationship("Invitation", back_populates="candidate")
    events = relationship("CandidateEvent", back_populates="candidate")
    conversation_messages = relationship("ConversationMessage", back_populates="candidate")
    inbound_messages = relationship("InboundMessage", back_populates="candidate")
```

Create `app/models/interviewer.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Interviewer(Base):
    __tablename__ = "interviewers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    slots = relationship("Slot", back_populates="interviewer")
```

Create `app/models/slot.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    interviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("interviewers.id"), nullable=False)
    start_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="video", nullable=False)
    location_or_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="slots")
    interviewer = relationship("Interviewer", back_populates="slots")
    booking = relationship("Booking", back_populates="slot", uselist=False)
```

Create `app/models/invitation.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    outcome: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    candidate = relationship("Candidate", back_populates="invitations")
```

Create `app/models/booking.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=False)
    slot_id: Mapped[str] = mapped_column(String(36), ForeignKey("slots.id"), nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)

    candidate = relationship("Candidate", back_populates="bookings")
    slot = relationship("Slot", back_populates="booking")
```

Create `app/models/email_outbox.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    to_address: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Create `app/models/inbound_message.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InboundMessage(Base):
    __tablename__ = "inbound_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=True)
    from_address: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    candidate = relationship("Candidate", back_populates="inbound_messages")
```

Create `app/models/conversation_message.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    outbox_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("email_outbox.id"), nullable=True)
    inbound_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("inbound_messages.id"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="conversation_messages")
```

Create `app/models/candidate_event.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CandidateEvent(Base):
    __tablename__ = "candidate_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="events")
```

Create `app/models/__init__.py`:
```python
from app.models.job import Job
from app.models.candidate import Candidate
from app.models.interviewer import Interviewer
from app.models.slot import Slot
from app.models.invitation import Invitation
from app.models.booking import Booking
from app.models.email_outbox import EmailOutbox
from app.models.inbound_message import InboundMessage
from app.models.conversation_message import ConversationMessage
from app.models.candidate_event import CandidateEvent

__all__ = [
    "Job", "Candidate", "Interviewer", "Slot", "Invitation",
    "Booking", "EmailOutbox", "InboundMessage", "ConversationMessage",
    "CandidateEvent",
]
```

- [ ] **Step 7: Create app/main.py skeleton**

```python
from fastapi import FastAPI
from app.database import Base, engine

app = FastAPI(title="Recruitment Agent", version="0.1.0")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 8: Create tests/conftest.py**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
```

- [ ] **Step 9: Write test for model creation**

Create `tests/test_models.py`:
```python
from app.models import Job, Candidate


def test_all_tables_created(db_session):
    tables = db_session.bind.dialect.get_table_names(db_session.bind.connect())
    expected = [
        "jobs", "candidates", "interviewers", "slots", "invitations",
        "bookings", "email_outbox", "inbound_messages",
        "conversation_messages", "candidate_events",
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
```

- [ ] **Step 10: Run tests**

Run: `cd C:\Users\FAROOQUE\.gemini\antigravity-ide\scratch\recruitment-agent && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git init && git add . && git commit -m "feat: project foundation — config, database, all 10 models"
```

---

### Task 2: State Machine

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/state_machine.py`
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Consumes: `Candidate`, `CandidateEvent` models from Task 1
- Produces: `transition_candidate(db, candidate_id, new_status, actor, payload) -> Candidate`, `IllegalTransition`, `CandidateStatus`, `LEGAL_TRANSITIONS`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state_machine.py`:
```python
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
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_state_machine.py -v`

- [ ] **Step 3: Implement state_machine.py**

Create `app/services/__init__.py` (empty) and `app/services/state_machine.py`:
```python
from app.models import Candidate, CandidateEvent


class CandidateStatus:
    NEW = "NEW"
    SHORTLISTED = "SHORTLISTED"
    INVITED = "INVITED"
    BOOKED = "BOOKED"
    INTERVIEWED = "INTERVIEWED"
    DECLINED = "DECLINED"
    NEEDS_RECRUITER = "NEEDS_RECRUITER"
    FOLLOW_UP = "FOLLOW_UP"
    NO_RESPONSE = "NO_RESPONSE"
    WAITLISTED = "WAITLISTED"


class IllegalTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Illegal transition: {from_status} -> {to_status}")


LEGAL_TRANSITIONS: dict[tuple[str, str], set[str]] = {
    (CandidateStatus.NEW, CandidateStatus.SHORTLISTED): {"recruiter"},
    (CandidateStatus.NEW, CandidateStatus.WAITLISTED): {"recruiter"},
    (CandidateStatus.SHORTLISTED, CandidateStatus.INVITED): {"system"},
    (CandidateStatus.INVITED, CandidateStatus.BOOKED): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.DECLINED): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.NEEDS_RECRUITER): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.INVITED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.BOOKED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.DECLINED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.NEEDS_RECRUITER): {"agent"},
    (CandidateStatus.BOOKED, CandidateStatus.INTERVIEWED): {"recruiter"},
}


def transition_candidate(db, candidate_id: str, new_status: str, actor: str, payload: dict | None = None) -> Candidate:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")

    key = (candidate.status, new_status)
    allowed_actors = LEGAL_TRANSITIONS.get(key)
    if allowed_actors is None or actor not in allowed_actors:
        raise IllegalTransition(candidate.status, new_status)

    candidate.status = new_status
    event = CandidateEvent(
        candidate_id=candidate_id, event_type=new_status.lower(), actor=actor, payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(candidate)
    return candidate
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_state_machine.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/services/ tests/test_state_machine.py && git commit -m "feat: state machine with legal transitions and tests"
```

---

### Task 3: Candidate Service + Mock Generator

**Files:**
- Create: `app/services/candidate_service.py`
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/candidate.py`
- Test: `tests/test_candidate_service.py`

**Interfaces:**
- Consumes: `Candidate`, `Job` models, `transition_candidate()` from Task 2
- Produces: `CandidateService.generate_mock(db, job_id, count)`, `CandidateService.create_from_api(db, job_id, data)`, `CandidateService.get_by_job(db, job_id, ...)`, `CandidateCreate` schema

- [ ] **Step 1: Write failing tests**

Create `tests/test_candidate_service.py`:
```python
import pytest
from app.models import Job
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
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement CandidateService**

Create `app/schemas/__init__.py` (empty), `app/schemas/candidate.py` with `CandidateCreate` model, and `app/services/candidate_service.py` with `generate_mock()` using Faker (en_IN locale), skill pool matching by job title keywords, salary scaling by experience (₹4L–₹40L), and `get_by_job()` with pagination and status filter. See spec for SKILL_POOLS and INDIAN_COMPANIES constants.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/candidate_service.py app/schemas/ tests/test_candidate_service.py
git commit -m "feat: candidate service with mock generator"
```

---

### Task 4: Slot Service + Atomic Booking

**Files:**
- Create: `app/services/slot_service.py`
- Create: `app/schemas/slot.py`
- Test: `tests/test_booking.py`

**Interfaces:**
- Consumes: `Slot`, `Booking`, `Interviewer` models, `transition_candidate()` from Task 2
- Produces: `SlotService.create_slots(db, job_id, interviewer_id, start, end, duration)`, `SlotService.get_available(db, job_id) -> list[dict]` (each dict has label A/B/C), `SlotService.book(db, slot_id, candidate_id) -> (bool, Booking|str)`, `SlotService.cancel(db, slot_id)`

- [ ] **Step 1: Write failing tests**

Create `tests/test_booking.py` with tests for: `create_slots_from_window`, `book_slot_atomically`, `double_booking_prevented`, `get_available_returns_only_open`, `cancel_slot`. See spec Task 4 for full test code using atomic `UPDATE WHERE status='open'`.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement SlotService**

Create `app/services/slot_service.py` with atomic booking via `db.execute(update(Slot).where(Slot.id == slot_id, Slot.status == "open").values(status="booked"))` and row count check. `get_available()` labels slots A, B, C... in chronological order. Create `app/schemas/slot.py` with `SlotCreate` model.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/slot_service.py app/schemas/slot.py tests/test_booking.py
git commit -m "feat: slot service with atomic booking"
```

---

### Task 5: Invitation Service + Email Service + Mock Provider

**Files:**
- Create: `app/services/invitation_service.py`
- Create: `app/services/email_service.py`
- Create: `app/providers/__init__.py`
- Create: `app/providers/email_provider.py`
- Create: `app/providers/inbox_provider.py`
- Test: `tests/test_invitation.py`

**Interfaces:**
- Consumes: `Invitation`, `EmailOutbox`, `ConversationMessage` models, `SlotService.get_available()` from Task 4
- Produces: `InvitationService.create_invitation(db, candidate_id) -> (Invitation, raw_token)`, `InvitationService.validate_token(db, raw_token) -> Invitation|None`, `EmailService.enqueue(...)`, `EmailService.enqueue_invitation_batch(...)`, `EmailService.drain_outbox(...)`, `MockEmailProvider`, `MockInboxProvider`

- [ ] **Step 1: Write failing tests**

Create `tests/test_invitation.py` with tests for: `create_invitation_returns_token`, `token_hash_stored_not_raw`, `validate_valid_token`, `validate_invalid_token`, `validate_empty_token`. Token is `secrets.token_urlsafe(32)`, stored as SHA-256 hash.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement InvitationService, EmailService, MockEmailProvider, MockInboxProvider**

See spec Task 5 for full code. `EmailService.enqueue_invitation_batch()` generates slot list (A, B, C...) in the email body and includes fallback token link. `MockEmailProvider` logs to console. `MockInboxProvider.poll()` returns empty (mock inbox page writes directly to DB).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/invitation_service.py app/services/email_service.py app/providers/
git commit -m "feat: invitation service, email outbox, mock providers"
```

---

### Task 6: Agent Worker + Agent Service Stub + Tools

**Files:**
- Create: `app/agent/__init__.py`
- Create: `app/agent/worker.py`
- Create: `app/agent/tools.py`
- Create: `app/services/agent_service.py`
- Create: `app/schemas/agent.py`
- Create: `app/providers/llm_provider.py`

**Interfaces:**
- Consumes: `EmailService.drain_outbox()` from Task 5, `InboundMessage` model, `SlotService`, `transition_candidate()`
- Produces: `agent_tick()` for APScheduler, `AgentService.process_reply(db, msg_id)` (stub — marks processed, logs event, no LLM), `AgentDecision` Pydantic schema, `AgentTools` class with `get_candidate_context`, `get_open_slots`, `book_slot`, `send_email`, `mark_declined`, `escalate_to_recruiter`

- [ ] **Step 1: Create AgentDecision schema** with Pydantic validator: `intent: choose|decline|none_fit|unclear`, `slot_label` required for choose, `confidence: float`.

- [ ] **Step 2: Create NoOpLLMProvider** stub.

- [ ] **Step 3: Create AgentTools** with all 6 methods scoped to one candidate. `book_slot()` validates label, calls `SlotService.book()`, transitions on success, returns remaining slots on failure.

- [ ] **Step 4: Create AgentService** stub: `process_reply()` marks `processed=True`, creates `ConversationMessage` + `CandidateEvent` with note "LLM not active".

- [ ] **Step 5: Create agent worker** with APScheduler: `agent_tick()` drains outbox, polls inbox (empty in P1), processes unprocessed messages. `start_scheduler()` and `stop_scheduler()` functions.

- [ ] **Step 6: Commit**

```bash
git add app/agent/ app/services/agent_service.py app/schemas/agent.py app/providers/llm_provider.py
git commit -m "feat: agent worker, tools, service stub"
```

---

### Task 7: Export Service

**Files:**
- Create: `app/services/export_service.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Job`, `Candidate`, `Slot`, `Booking`, `Interviewer`, `ConversationMessage` models
- Produces: `ExportService.export_job(db, job_id) -> openpyxl.Workbook` with 3 sheets: Schedule, Not Scheduled, Conversation Log

- [ ] **Step 1: Write failing tests**

Create `tests/test_export.py` with tests for: `has_three_sheets`, `schedule_has_booked`, `not_scheduled_has_declined`, `conversation_log_has_messages`. Set up a populated job fixture with candidates in various states + conversation messages.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement ExportService**

3 sheets: **Schedule** (Date, Time, Interviewer, Candidate, Email, Mode, Link), **Not Scheduled** (Name, Email, Status, Reason), **Conversation Log** (Candidate, Direction, Summary, Timestamp). Dark header styling with openpyxl Font + PatternFill. Auto-width columns.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/export_service.py tests/test_export.py
git commit -m "feat: Excel export with 3 sheets"
```

---

### Task 8: Auth + CSS Design System + Base Template

**Files:**
- Create: `app/routes/__init__.py`
- Create: `app/routes/auth.py`
- Create: `app/static/css/style.css`
- Create: `app/static/js/app.js`
- Create: `app/templates/base.html`
- Create: `app/templates/admin/login.html`
- Modify: `app/main.py` — add static files, session middleware, auth router, scheduler startup

**Interfaces:**
- Consumes: `Settings` from Task 1
- Produces: `login_required` dependency, `/admin/login`, `/admin/logout`, `base.html` layout, `style.css` design system

- [ ] **Step 1: Create auth routes** — `login_required` checks `request.session["authenticated"]`, raises 303 redirect. Login validates bcrypt hash. Logout clears session.

- [ ] **Step 2: Create base.html** — HTML5, Inter font, HTMX script, sidebar nav (Dashboard, Interviewers, Mock Inbox), main content area, toast container.

- [ ] **Step 3: Create login.html** — extends base (no sidebar), login card with username/password form, error display.

- [ ] **Step 4: Create style.css** — 400+ lines. Dark theme CSS custom properties (all status colors from spec as HSL), sidebar layout, btn variants, badges, data tables, forms, cards, alerts, toasts, login page, responsive breakpoints.

- [ ] **Step 5: Create app.js** — Timezone detection, HTMX toast handler, `showToast()` function.

- [ ] **Step 6: Update main.py** — add `SessionMiddleware`, mount `/static`, include `auth.router`, add `lifespan` handler that calls `start_scheduler()` on startup and `stop_scheduler()` on shutdown, `Base.metadata.create_all()`.

- [ ] **Step 7: Verify** — start app, visit `/admin/login`, login works, logout redirects.

- [ ] **Step 8: Commit**

```bash
git add app/routes/auth.py app/templates/ app/static/ app/main.py
git commit -m "feat: auth, base template, CSS design system"
```

---

### Task 9: Admin Dashboard + Job + Candidate Pages

**Files:**
- Create: `app/routes/admin.py`
- Create: `app/schemas/job.py`
- Create: `app/templates/admin/dashboard.html`
- Create: `app/templates/admin/job_detail.html`
- Modify: `app/main.py` — include admin router

**Interfaces:**
- Consumes: `login_required` from Task 8, `Job`, `Candidate` models, `CandidateService` from Task 3, `transition_candidate()` from Task 2
- Produces: `GET /admin/`, `POST /admin/jobs`, `GET /admin/jobs/{id}`, `POST /admin/jobs/{id}/generate-candidates`, `POST /admin/candidates/{id}/shortlist`, `POST /admin/candidates/bulk-shortlist`

- [ ] **Step 1: Create job schema** — `JobCreate(title, description)`, `JobUpdate(title?, description?, status?)`.

- [ ] **Step 2: Create admin.py** — Dashboard shows job cards with status counts. Job detail has tabbed layout (Candidates, Slots, Invite, Export). Candidate table with checkboxes, status badges, shortlist action. Generate candidates button. HTMX partials on HX-Request.

- [ ] **Step 3: Create dashboard.html** — extends base. Grid of job cards, each with title, status, count badges. Create job modal form.

- [ ] **Step 4: Create job_detail.html** — extends base. Job header, tab bar, candidates tab as default. Data table, bulk shortlist, status filter pills.

- [ ] **Step 5: Register admin router** in main.py.

- [ ] **Step 6: Test manually** — login, create job, generate candidates, shortlist, filter.

- [ ] **Step 7: Commit**

```bash
git add app/routes/admin.py app/schemas/job.py app/templates/admin/
git commit -m "feat: admin dashboard, job CRUD, candidate management"
```

---

### Task 10: Admin Slots + Interviewers + Invitations

**Files:**
- Create: `app/templates/admin/interviewers.html`
- Create: `app/templates/admin/invite_preview.html`
- Create: `app/templates/emails/invitation.html`
- Modify: `app/routes/admin.py` — add slot, interviewer, invitation routes

**Interfaces:**
- Consumes: `SlotService` from Task 4, `EmailService` from Task 5, `InvitationService` from Task 5
- Produces: Slot CRUD, interviewer CRUD, invitation preview + batch send, export download, manual booking

- [ ] **Step 1: Add slot routes** — `GET/POST /admin/jobs/{id}/slots`, `DELETE /admin/slots/{id}`. Create form takes interviewer, date, start/end time, duration.

- [ ] **Step 2: Add interviewer routes** — `GET /admin/interviewers`, `POST /admin/interviewers`. Shared across jobs.

- [ ] **Step 3: Add invitation routes** — `GET /admin/jobs/{id}/invite-preview` shows shortlisted candidates + available slots. `POST /admin/jobs/{id}/send-invitations` enqueues batch and transitions to INVITED.

- [ ] **Step 4: Add export + manual book routes** — `GET /admin/jobs/{id}/export` returns StreamingResponse Excel. `POST /admin/candidates/{id}/book` with slot_id form field.

- [ ] **Step 5: Create templates** — interviewers.html (CRUD table), invite_preview.html (candidate list + slot list + send button), invitation.html email template.

- [ ] **Step 6: Test manually** — add interviewer, create slots, preview, send invitations.

- [ ] **Step 7: Commit**

```bash
git add app/routes/admin.py app/templates/
git commit -m "feat: slots, interviewers, invitation sending, export download"
```

---

### Task 11: Conversations + Mock Inbox Page

**Files:**
- Create: `app/routes/mock_inbox.py`
- Create: `app/templates/admin/conversations.html`
- Create: `app/templates/admin/mock_inbox.html`
- Modify: `app/main.py` — include mock_inbox router

**Interfaces:**
- Consumes: `InboundMessage`, `ConversationMessage` models, `MOCK_INBOX` config, `AgentService` from Task 6
- Produces: `GET /admin/jobs/{id}/conversations`, `GET /admin/mock-inbox`, `POST /admin/mock-inbox/{candidate_id}/reply`

- [ ] **Step 1: Add conversations route** to admin.py — shows per-candidate timeline of sent/received messages.

- [ ] **Step 2: Create mock_inbox.py** — `GET /admin/mock-inbox` shows INVITED/FOLLOW_UP candidates with threads + reply textarea. `POST reply` creates `InboundMessage` + `ConversationMessage`. Both routes require `login_required` AND `settings.mock_inbox == True`.

- [ ] **Step 3: Create mock_inbox.html** — conversation bubbles (outbound = right, inbound = left), reply form per candidate. Disabled message when `MOCK_INBOX=false`.

- [ ] **Step 4: Create conversations.html** — expandable rows per candidate, message timeline.

- [ ] **Step 5: Register router**, test full flow: invite → mock inbox → reply → message stored.

- [ ] **Step 6: Commit**

```bash
git add app/routes/mock_inbox.py app/templates/admin/ app/main.py
git commit -m "feat: mock inbox page and conversation threads"
```

---

### Task 12: Fallback Token Pages + API Ingestion

**Files:**
- Create: `app/routes/public.py`
- Create: `app/routes/api.py`
- Create: `app/templates/public/booking.html`
- Create: `app/templates/public/confirmed.html`
- Create: `app/templates/public/declined.html`
- Create: `app/templates/public/expired.html`
- Modify: `app/main.py` — include public + api routers

**Interfaces:**
- Consumes: `InvitationService.validate_token()` from Task 5, `SlotService.book()` from Task 4, `transition_candidate()` from Task 2, `CandidateService.create_from_api()` from Task 3
- Produces: `GET /i/{token}`, `POST /i/{token}/book`, `POST /i/{token}/decline`, `POST /i/{token}/none-work`, `GET /i/{token}/confirmed`, `POST /api/jobs/{id}/candidates`

- [ ] **Step 1: Create public.py** — validate token on every route, booking page shows slots, book atomically + transition, decline + transition, none-work + escalate. Light theme templates.

- [ ] **Step 2: Create api.py** — `POST /api/jobs/{id}/candidates` accepts `list[CandidateCreate]`, returns created count.

- [ ] **Step 3: Create public templates** — booking.html (light theme, mobile-friendly, slot cards, confirm modal), confirmed.html (success with details), declined.html (confirmation), expired.html (friendly error).

- [ ] **Step 4: Register routers** in main.py.

- [ ] **Step 5: Test** — open fallback link, book, decline, invalid token. POST API with httpx/curl.

- [ ] **Step 6: Commit**

```bash
git add app/routes/public.py app/routes/api.py app/templates/public/ app/main.py
git commit -m "feat: fallback token pages, API ingestion endpoint"
```

---

### Task 13: Agent Decision Schema + Parsing Tests

**Files:**
- Create: `tests/test_agent_parsing.py`

**Interfaces:**
- Consumes: `AgentDecision` from Task 6, `AgentTools.book_slot()` from Task 6

- [ ] **Step 1: Write tests**

Create `tests/test_agent_parsing.py`:
- `test_choose_requires_slot_label` — `AgentDecision(intent="choose", confidence=0.9)` raises `ValidationError`
- `test_choose_with_slot_label_valid` — works
- `test_invalid_intent_rejected` — `intent="hack"` raises `ValidationError`
- `test_wrong_slot_letter` — `tools.book_slot(cid, "Z")` returns `{success: False, remaining_slots: ["A","B","C"]}`
- `test_slot_already_taken` — first booking succeeds, second fails, remaining excludes taken slot
- `test_injection_attempt_schema` — `AgentDecision(intent="unclear", confidence=0.3)` valid but below threshold → would trigger escalation

- [ ] **Step 2: Run tests — expect PASS**

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_parsing.py && git commit -m "feat: agent parsing and schema validation tests"
```

---

### Final: End-to-End Verification

- [ ] **Step 1:** Start app: `python -m uvicorn app.main:app --reload --port 8000`

- [ ] **Step 2:** Walk full flow:
  1. Login → Create job → Generate 20 candidates
  2. Add interviewer → Create time slots
  3. Shortlist 5 candidates → Preview invitations → Send
  4. Mock Inbox → Type reply as candidate → Message stored
  5. Open fallback token link → Book slot → Confirmed
  6. Dashboard shows updated statuses
  7. Export Excel → Verify 3 sheets
  8. API: POST candidates via curl/httpx

- [ ] **Step 3:** Run all tests: `python -m pytest tests/ -v --tb=short` — ALL PASS

- [ ] **Step 4:** Final commit: `git add -A && git commit -m "feat: Phase 1 complete"`
