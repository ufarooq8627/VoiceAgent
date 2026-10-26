import pytest
from fastapi.testclient import TestClient
from app.services.widget_token_service import mint_widget_session_token, verify_widget_session_token
from app.models.receptionist import Business
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_widget_session_token_roundtrip():
    token = mint_widget_session_token(
        business_id="biz-123",
        origin="https://apexclinic.com",
        client_ip="192.168.1.1",
        ttl_seconds=600
    )
    payload = verify_widget_session_token(token)
    assert payload["business_id"] == "biz-123"
    assert payload["origin"] == "https://apexclinic.com"
    assert "exp" in payload

def test_widget_session_token_invalid():
    with pytest.raises(ValueError):
        verify_widget_session_token("invalid.token.here")

def test_init_widget_session_endpoint_allowed_origin(client, db_session):
    biz = Business(name="Apex Medical Clinic")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key_entry = ClientApiKey(
        business_id=biz.id,
        public_key=pub,
        secret_key_hash=sec_hash,
        name="Apex Web",
        allowed_origins=["https://apexclinic.com"],
        is_active=True
    )
    db_session.add(key_entry)
    db_session.commit()

    # 1. Allowed origin
    res = client.post(
        "/api/v1/widget/session",
        headers={"X-Client-Key": pub, "Origin": "https://apexclinic.com"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "session_token" in data
    assert data["business_id"] == biz.id
    assert data["business_name"] == "Apex Medical Clinic"
    assert data["expires_in"] == 900

    # 2. Origin not whitelisted
    res_bad_origin = client.post(
        "/api/v1/widget/session",
        headers={"X-Client-Key": pub, "Origin": "https://hacker.com"}
    )
    assert res_bad_origin.status_code == 403
    assert "not whitelisted" in res_bad_origin.json()["detail"]

    # 3. Invalid key
    res_bad_key = client.post(
        "/api/v1/widget/session",
        headers={"X-Client-Key": "pk_live_fake123", "Origin": "https://apexclinic.com"}
    )
    assert res_bad_key.status_code == 403
