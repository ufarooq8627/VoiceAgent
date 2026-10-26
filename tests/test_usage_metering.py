import pytest
from app.models.receptionist import Business
from app.models.client_api_key import ClientApiKey, generate_client_keys
from app.models.client_usage import ClientUsage
from app.services.usage_meter_service import check_and_increment_usage

def test_usage_meter_blocks_at_quota(db_session):
    biz = Business(name="Capped Clinic")
    db_session.add(biz)
    db_session.flush()

    # Pre-set quota to 2 calls
    usage = ClientUsage(
        business_id=biz.id,
        billing_period="2026-10",
        calls_used=2,
        quota_limit=2
    )
    db_session.add(usage)
    db_session.commit()

    allowed, reason = check_and_increment_usage(db_session, biz.id, period="2026-10")
    assert allowed is False
    assert "quota exceeded" in reason.lower()

def test_usage_meter_allows_and_increments(db_session):
    biz = Business(name="Growing Clinic")
    db_session.add(biz)
    db_session.flush()

    # Brand new client -> quota should initialize and allow
    allowed, msg = check_and_increment_usage(db_session, biz.id, period="2026-10")
    assert allowed is True

    record = db_session.query(ClientUsage).filter(
        ClientUsage.business_id == biz.id,
        ClientUsage.billing_period == "2026-10"
    ).first()
    assert record is not None
    assert record.calls_used == 1

def test_widget_call_start_returns_429_when_quota_exceeded(client, db_session):
    biz = Business(name="Exceeded Biz")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, allowed_origins=["*"])
    usage = ClientUsage(business_id=biz.id, billing_period="2026-10", calls_used=50, quota_limit=50)
    db_session.add_all([key, usage])
    db_session.commit()

    # Session
    res_sess = client.post("/api/v1/widget/session", headers={"X-Client-Key": pub, "Origin": "https://test.com"})
    token = res_sess.json()["session_token"]

    # Attempt to start call -> must fail with 429
    res_call = client.post(
        "/api/v1/widget/call/start",
        json={"caller_name": "Visitor"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_call.status_code == 429
    assert "quota exceeded" in res_call.json()["detail"].lower()
