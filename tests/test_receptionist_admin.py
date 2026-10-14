import io
import pytest
from datetime import datetime, timezone
import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models.receptionist import Business, Call, UnansweredEnquiry, KnowledgeItem
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
    biz = Business(id="biz-200", name="Apex Downtown", timezone="UTC")
    db.add(biz)
    call = Call(
        id="call-200",
        business_id="biz-200",
        provider_call_id="call-mock-200",
        caller_number="+15554443333",
        outcome="completed",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    enquiry = UnansweredEnquiry(
        id="enq-200",
        business_id="biz-200",
        call_id="call-200",
        question="Can I park in the underground garage?",
        failure_reason="no_approved_kb",
        status="pending",
    )
    db.add(enquiry)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_list_enquiries_page(client):
    res = client.get("/admin/receptionist/enquiries")
    assert res.status_code == 200
    assert "Can I park in the underground garage?" in res.text
    assert "+15554443333" in res.text


def test_resolve_enquiry_and_publish_kb(client):
    res = client.post(
        "/admin/receptionist/enquiries/enq-200/resolve",
        data={
            "owner_answer": "Yes, visitor parking is free on level B2.",
            "publish_to_kb": "true",
        },
        follow_redirects=False,
    )
    assert res.status_code in [200, 302, 303]

    db = TestingSessionLocal()
    enq = db.query(UnansweredEnquiry).filter(UnansweredEnquiry.id == "enq-200").first()
    assert enq.status == "resolved"
    assert enq.owner_answer == "Yes, visitor parking is free on level B2."

    # Verify KnowledgeItem was auto-published
    kb = db.query(KnowledgeItem).filter(
        KnowledgeItem.business_id == "biz-200",
        KnowledgeItem.question == "Can I park in the underground garage?",
    ).first()
    assert kb is not None
    assert kb.answer == "Yes, visitor parking is free on level B2."
    assert kb.status == "approved"
    db.close()


def test_export_excel_11_columns(client):
    res = client.get("/admin/receptionist/export")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    sheet = wb.active
    headers = [cell.value for cell in sheet[1]]

    expected_headers = [
        "enquiry_id",
        "business_id",
        "business_name",
        "call_id",
        "caller_phone",
        "question",
        "status",
        "owner_answer",
        "created_at",
        "resolved_at",
        "published_to_kb",
    ]
    assert headers == expected_headers

    # Check row 2 content
    row2 = [cell.value for cell in sheet[2]]
    assert row2[0] == "enq-200"
    assert row2[2] == "Apex Downtown"
    assert row2[4] == "+15554443333"
    assert row2[5] == "Can I park in the underground garage?"
    assert row2[6] == "pending"
