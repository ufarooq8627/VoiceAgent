import pytest
from app.models.receptionist import Business, Call, CallbackRequest, UnansweredEnquiry
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_portal_calls_and_leads_views(client, db_session):
    biz = Business(name="Luxe Salon")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, is_active=True)
    call = Call(
        business_id=biz.id,
        provider_call_id="call-luxe-1",
        caller_number="web_caller",
        outcome="completed",
        transcript=[
            {"role": "agent", "content": "Welcome to Luxe Salon!"},
            {"role": "caller", "content": "How much for a haircut?"},
            {"role": "agent", "content": "Haircuts start at $60."}
        ]
    )
    db_session.add_all([key, call])
    db_session.flush()

    cb = CallbackRequest(
        business_id=biz.id,
        call_id=call.id,
        customer_name="Jessica",
        callback_number="+15554443333",
        status="pending"
    )
    ue = UnansweredEnquiry(
        business_id=biz.id,
        call_id=call.id,
        question="Do you do Japanese hair straightening?",
        failure_reason="unknown_faq"
    )
    db_session.add_all([cb, ue])
    db_session.commit()

    # Login
    res_login = client.post("/portal/login", data={"client_secret": sec}, follow_redirects=False)
    cookies = res_login.cookies

    # 1. Calls list
    res_calls = client.get("/portal/calls", cookies=cookies)
    assert res_calls.status_code == 200
    assert "call-luxe-1" in res_calls.text

    # 2. Single Call Transcript
    res_single = client.get(f"/portal/calls/{call.id}", cookies=cookies)
    assert res_single.status_code == 200
    assert "Haircuts start at $60." in res_single.text

    # 3. Leads View
    res_leads = client.get("/portal/leads", cookies=cookies)
    assert res_leads.status_code == 200
    assert "Jessica" in res_leads.text
    assert "+15554443333" in res_leads.text
    assert "Japanese hair straightening" in res_leads.text

    # 4. Update callback status to 'contacted'
    res_status = client.post(
        f"/portal/leads/callback/{cb.id}/status",
        data={"status": "contacted"},
        cookies=cookies,
        follow_redirects=False
    )
    assert res_status.status_code in [302, 303]
    db_session.refresh(cb)
    assert cb.status == "contacted"

def test_portal_calls_tenant_isolation(client, db_session):
    biz_a = Business(name="Salon A")
    biz_b = Business(name="Salon B")
    db_session.add_all([biz_a, biz_b])
    db_session.flush()

    pub_a, sec_a, hash_a = generate_client_keys()
    key_a = ClientApiKey(business_id=biz_a.id, public_key=pub_a, secret_key_hash=hash_a, is_active=True)
    call_a = Call(business_id=biz_a.id, provider_call_id="call-secret-a", caller_number="web_caller")

    pub_b, sec_b, hash_b = generate_client_keys()
    key_b = ClientApiKey(business_id=biz_b.id, public_key=pub_b, secret_key_hash=hash_b, is_active=True)

    db_session.add_all([key_a, call_a, key_b])
    db_session.commit()

    # Login as Tenant B
    res_login_b = client.post("/portal/login", data={"client_secret": sec_b}, follow_redirects=False)
    cookies_b = res_login_b.cookies

    # Attempt to view Tenant A's call -> 404
    res = client.get(f"/portal/calls/{call_a.id}", cookies=cookies_b)
    assert res.status_code == 404
