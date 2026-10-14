import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models.receptionist import Business, BusinessPhoneNumber, Call
from app.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    biz = Business(
        id="biz-100",
        name="Apex Dental Care",
        timezone="America/New_York",
    )
    db.add(biz)
    phone = BusinessPhoneNumber(
        id="phone-100",
        business_id="biz-100",
        phone_number="+15550001111",
        active=True,
    )
    db.add(phone)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_start_call_registered_and_unregistered(client):
    # Registered number
    res = client.post(
        "/api/receptionist/calls/start",
        json={
            "dialed_number": "+15550001111",
            "caller_number": "+15559998888",
            "caller_name": "Alice Smith",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "call_id" in data
    assert data["business_id"] == "biz-100"
    assert "Apex Dental Care" in data["greeting"]
    assert "AI" in data["greeting"]

    # Unregistered number
    res2 = client.post(
        "/api/receptionist/calls/start",
        json={
            "dialed_number": "+19999999999",
            "caller_number": "+15559998888",
        },
    )
    assert res2.status_code == 404


def test_call_turn_flow(client):
    # Start call first
    res = client.post(
        "/api/receptionist/calls/start",
        json={"dialed_number": "+15550001111", "caller_number": "+15559998888"},
    )
    call_id = res.json()["call_id"]

    # Send turn
    turn_res = client.post(
        f"/api/receptionist/calls/{call_id}/turn",
        json={"caller_message": "What time do you open tomorrow?"},
    )
    assert turn_res.status_code == 200
    data = turn_res.json()
    assert "reply_text" in data
    assert isinstance(data["tools_called"], list)

    # Verify Call transcript updated in DB
    db = TestingSessionLocal()
    call = db.query(Call).filter(Call.id == call_id).first()
    assert call is not None
    assert len(call.transcript) >= 2
    assert call.transcript[0]["role"] == "caller"
    assert "What time do you open" in call.transcript[0]["content"]
    assert call.transcript[1]["role"] == "agent"
    db.close()


def test_end_call_flow(client):
    res = client.post(
        "/api/receptionist/calls/start",
        json={"dialed_number": "+15550001111", "caller_number": "+15559998888"},
    )
    call_id = res.json()["call_id"]

    end_res = client.post(
        f"/api/receptionist/calls/{call_id}/end",
        json={"summary": "Caller enquired about opening hours."},
    )
    assert end_res.status_code == 200
    data = end_res.json()
    assert data["status"] == "completed"

    db = TestingSessionLocal()
    call = db.query(Call).filter(Call.id == call_id).first()
    assert call.outcome == "completed"
    assert call.ended_at is not None
    assert call.summary == "Caller enquired about opening hours."
    db.close()


def test_mock_call_simulator_page_renders(client):
    res = client.get("/admin/mock-call")
    assert res.status_code == 200
    assert "Voice Receptionist Simulator" in res.text
