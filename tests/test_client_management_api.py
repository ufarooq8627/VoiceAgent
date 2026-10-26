import pytest
from app.models.receptionist import Business, KnowledgeItem, CallbackRequest, UnansweredEnquiry, Call
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_client_knowledge_sync(client, db_session):
    biz = Business(name="Client Co")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, is_active=True)
    db_session.add(key)
    db_session.commit()

    # 1. Sync FAQs via Client Secret
    items = [
        {"question": "What is the return policy?", "answer": "30 days no questions asked.", "category": "policy"},
        {"question": "Do you offer free shipping?", "answer": "Yes on orders over $50.", "category": "shipping"}
    ]
    res = client.post(
        "/api/v1/client/knowledge/sync",
        json={"items": items},
        headers={"X-Client-Secret": sec}
    )
    assert res.status_code == 200
    assert res.json()["synced_count"] == 2

    # Query DB to verify persistence
    faqs = db_session.query(KnowledgeItem).filter(KnowledgeItem.business_id == biz.id).all()
    assert len(faqs) == 2
    answers = [f.answer for f in faqs]
    assert "30 days no questions asked." in answers

def test_client_leads_retrieval(client, db_session):
    biz = Business(name="Lead Corp")
    db_session.add(biz)
    db_session.flush()

    call = Call(business_id=biz.id, provider_call_id="call-lead-1", caller_number="+15551234567")
    db_session.add(call)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, is_active=True)
    cb = CallbackRequest(business_id=biz.id, call_id=call.id, customer_name="Alice Smith", callback_number="+15551234567")
    ue = UnansweredEnquiry(business_id=biz.id, call_id=call.id, question="Do you support crypto payments?", failure_reason="unknown_faq")
    db_session.add_all([key, cb, ue])
    db_session.commit()

    res = client.get("/api/v1/client/leads", headers={"X-Client-Secret": sec})
    assert res.status_code == 200
    data = res.json()
    assert len(data["callbacks"]) == 1
    assert data["callbacks"][0]["customer_name"] == "Alice Smith"
    assert data["callbacks"][0]["callback_number"] == "+15551234567"
    assert len(data["unanswered"]) == 1
    assert data["unanswered"][0]["question"] == "Do you support crypto payments?"

def test_client_secret_invalid_rejected(client):
    res = client.post(
        "/api/v1/client/knowledge/sync",
        json={"items": []},
        headers={"X-Client-Secret": "sk_live_invalid_secret"}
    )
    assert res.status_code == 401
