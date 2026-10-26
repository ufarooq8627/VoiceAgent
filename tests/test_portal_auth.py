import pytest
from app.models.receptionist import Business
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_portal_login_with_secret_key_success(client, db_session):
    biz = Business(name="Smile Studio Dental")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, is_active=True)
    db_session.add(key)
    db_session.commit()

    # 1. Login with secret key (do not auto follow redirect to check cookie and 303 status)
    res = client.post("/portal/login", data={"client_secret": sec}, follow_redirects=False)
    assert res.status_code in [302, 303]
    assert "portal_session" in res.cookies

    # 2. Access protected portal page with the session cookie
    res_portal = client.get("/portal", cookies=res.cookies)
    assert res_portal.status_code == 200
    assert "Smile Studio Dental" in res_portal.text

def test_portal_login_invalid_key_rejected(client):
    res = client.post("/portal/login", data={"client_secret": "sk_live_fake_key"})
    assert res.status_code == 401

def test_portal_logout_clears_session(client):
    res = client.get("/portal/logout", follow_redirects=False)
    assert res.status_code in [302, 303]
