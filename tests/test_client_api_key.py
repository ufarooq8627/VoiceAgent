import pytest
from app.models.client_api_key import ClientApiKey, generate_client_keys, verify_client_secret
from app.models.receptionist import Business

def test_generate_client_keys_format():
    public_key, secret_key, secret_hash = generate_client_keys()
    assert public_key.startswith("pk_live_")
    assert secret_key.startswith("sk_live_")
    assert len(public_key) >= 32
    assert len(secret_key) >= 32
    assert secret_hash != secret_key
    assert verify_client_secret(secret_key, secret_hash) is True
    assert verify_client_secret("sk_live_invalid", secret_hash) is False

def test_client_api_key_persistence(db_session):
    biz = Business(name="Apex Medical Clinic")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key_entry = ClientApiKey(
        business_id=biz.id,
        public_key=pub,
        secret_key_hash=sec_hash,
        name="Main Website Key",
        allowed_origins=["https://apexclinic.com", "https://staging.apexclinic.com"],
        rate_limit_per_minute=100
    )
    db_session.add(key_entry)
    db_session.commit()

    saved = db_session.query(ClientApiKey).filter(ClientApiKey.public_key == pub).first()
    assert saved is not None
    assert saved.business_id == biz.id
    assert saved.name == "Main Website Key"
    assert "https://apexclinic.com" in saved.allowed_origins
    assert saved.is_active is True
    assert saved.business.name == "Apex Medical Clinic"
