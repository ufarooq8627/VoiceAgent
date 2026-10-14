import pytest
from datetime import datetime, timezone, timedelta
from app.models.receptionist import Business, KnowledgeItem, LiveDataSource
from app.services.knowledge_service import KnowledgeService
from app.services.live_data_adapter import LiveDataAdapter


@pytest.fixture
def test_biz(db_session):
    biz = Business(name="Grand Valley Hospital", timezone="UTC")
    db_session.add(biz)
    db_session.commit()
    return biz


def test_search_static_only_returns_approved_and_valid(db_session, test_biz):
    now = datetime.now(timezone.utc)
    # 1. Approved & currently valid
    k1 = KnowledgeItem(
        business_id=test_biz.id,
        question="What are visiting hours?",
        answer="Visiting hours are 10am to 8pm daily.",
        category="policy",
        status="approved",
        valid_from=now - timedelta(days=10),
        valid_until=now + timedelta(days=10),
    )
    # 2. Unapproved (pending) - must be ignored!
    k2 = KnowledgeItem(
        business_id=test_biz.id,
        question="What is the visiting hours policy?",
        answer="Draft answer: 24/7.",
        category="policy",
        status="pending_approval",
        valid_from=now - timedelta(days=1),
    )
    # 3. Expired - must be ignored!
    k3 = KnowledgeItem(
        business_id=test_biz.id,
        question="Special holiday visiting hours",
        answer="Holiday visiting hours are 12pm to 4pm.",
        category="policy",
        status="approved",
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )
    # 4. Future valid - must be ignored!
    k4 = KnowledgeItem(
        business_id=test_biz.id,
        question="New 2027 visiting hours",
        answer="Future hours.",
        category="policy",
        status="approved",
        valid_from=now + timedelta(days=5),
    )
    db_session.add_all([k1, k2, k3, k4])
    db_session.commit()

    results = KnowledgeService.search_static(db_session, test_biz.id, "visiting hours")
    assert len(results) == 1
    assert results[0]["id"] == k1.id
    assert "10am to 8pm" in results[0]["answer"]


def test_business_isolation_prevents_cross_leakage(db_session, test_biz):
    biz2 = Business(name="Other Clinic", timezone="UTC")
    db_session.add(biz2)
    db_session.commit()

    k_other = KnowledgeItem(
        business_id=biz2.id,
        question="What are visiting hours?",
        answer="Other clinic visiting hours: 2pm to 3pm only.",
        status="approved",
    )
    db_session.add(k_other)
    db_session.commit()

    # Search for test_biz must NOT return biz2's answer
    results = KnowledgeService.search_static(db_session, test_biz.id, "visiting hours")
    assert len(results) == 0


def test_bulk_import_csv_marks_as_unapproved(db_session, test_biz):
    csv_data = """question,answer,category
Where is the emergency room?,Building A Ground Floor,facilities
How do I pay my bill?,Online at hospital.com or at reception,billing
"""
    result = KnowledgeService.bulk_import_csv(db_session, test_biz.id, csv_data)
    assert result["success"] is True
    assert result["imported_count"] == 2

    items = db_session.query(KnowledgeItem).filter_by(business_id=test_biz.id).all()
    assert len(items) == 2
    # Section 7 requirement: Imported entries must remain unapproved until owner review
    assert all(item.status == "pending_approval" for item in items)


def test_live_data_adapter_freshness_validation(db_session, test_biz):
    source = LiveDataSource(
        business_id=test_biz.id,
        source_type="appointment_slots",
        capabilities={"pricing": True, "availability": True},
        config_reference="clinic_sim",
        active=True,
        freshness_limit_seconds=60,
    )
    db_session.add(source)
    db_session.commit()

    # Fresh query returns confirmed
    res_fresh = LiveDataAdapter.get_price_or_availability(
        db_session,
        business_id=test_biz.id,
        item_key="cardiology_consultation",
        requested_date="2026-10-15",
        force_stale=False,
    )
    assert res_fresh["status"] == "confirmed"
    assert res_fresh["price"] is not None
    assert res_fresh["availability_status"] in ("available", "sold_out")

    # Stale query returns unconfirmed
    res_stale = LiveDataAdapter.get_price_or_availability(
        db_session,
        business_id=test_biz.id,
        item_key="cardiology_consultation",
        requested_date="2026-10-15",
        force_stale=True,
    )
    assert res_stale["status"] == "unconfirmed"
    assert "stale" in res_stale.get("reason", "").lower()


def test_live_data_adapter_missing_source_returns_unconfirmed(db_session, test_biz):
    # No active LiveDataSource configured
    res = LiveDataAdapter.get_price_or_availability(
        db_session,
        business_id=test_biz.id,
        item_key="surgery_suite",
    )
    assert res["status"] == "unconfirmed"
