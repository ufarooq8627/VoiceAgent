import pytest
from app.models.receptionist import Business, Call, CallbackRequest
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_portal_dashboard_kpis_and_origins(client, db_session):
    biz = Business(name="Prime Aesthetics")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(
        business_id=biz.id,
        public_key=pub,
        secret_key_hash=sec_hash,
        allowed_origins=["https://prime.com"],
        is_active=True
    )
    call = Call(business_id=biz.id, provider_call_id="call-p1", caller_number="web_caller", outcome="completed")
    db_session.add_all([key, call])
    db_session.flush()

    cb = CallbackRequest(business_id=biz.id, call_id=call.id, customer_name="Eve", callback_number="+15550001111")
    db_session.add(cb)
    db_session.commit()

    # Login
    res_login = client.post("/portal/login", data={"client_secret": sec}, follow_redirects=False)
    cookies = res_login.cookies

    # View Dashboard
    res = client.get("/portal", cookies=cookies)
    assert res.status_code == 200
    assert "Prime Aesthetics" in res.text
    assert pub in res.text  # Embed snippet contains public key
    assert "https://prime.com" in res.text

    # Update Whitelisted Origins
    res_origins = client.post(
        "/portal/settings/origins",
        data={"allowed_origins": "https://prime.com, https://shop.prime.com"},
        cookies=cookies,
        follow_redirects=False
    )
    assert res_origins.status_code in [302, 303]

    # Verify updated in DB
    updated_key = db_session.query(ClientApiKey).filter(ClientApiKey.business_id == biz.id).first()
    assert "https://shop.prime.com" in updated_key.allowed_origins
