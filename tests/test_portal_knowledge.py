import pytest
from app.models.receptionist import Business, KnowledgeItem
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_portal_faq_crud_lifecycle(client, db_session):
    biz = Business(name="Dermatology Clinic")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, is_active=True)
    db_session.add(key)
    db_session.commit()

    # Login
    res_login = client.post("/portal/login", data={"client_secret": sec}, follow_redirects=False)
    cookies = res_login.cookies

    # 1. View Knowledge page (empty initially)
    res_list = client.get("/portal/knowledge", cookies=cookies)
    assert res_list.status_code == 200

    # 2. Add FAQ
    res_add = client.post(
        "/portal/knowledge/add",
        data={"question": "Do you accept walk-ins?", "answer": "Walk-ins are welcome between 10am and 2pm.", "category": "appointments"},
        cookies=cookies,
        follow_redirects=False
    )
    assert res_add.status_code in [302, 303]

    faq = db_session.query(KnowledgeItem).filter(KnowledgeItem.business_id == biz.id).first()
    assert faq is not None
    assert faq.question == "Do you accept walk-ins?"
    assert faq.status == "approved"

    # 3. Edit FAQ
    res_edit = client.post(
        f"/portal/knowledge/{faq.id}/edit",
        data={"question": "Do you accept walk-ins?", "answer": "Walk-ins accepted all day.", "category": "appointments"},
        cookies=cookies,
        follow_redirects=False
    )
    assert res_edit.status_code in [302, 303]
    db_session.refresh(faq)
    assert faq.answer == "Walk-ins accepted all day."

    # 4. Delete FAQ
    res_del = client.post(
        f"/portal/knowledge/{faq.id}/delete",
        cookies=cookies,
        follow_redirects=False
    )
    assert res_del.status_code in [302, 303]
    deleted = db_session.query(KnowledgeItem).filter(KnowledgeItem.id == faq.id).first()
    assert deleted is None

def test_portal_faq_cross_tenant_isolation(client, db_session):
    # Setup Tenant A with an FAQ
    biz_a = Business(name="Tenant A")
    biz_b = Business(name="Tenant B")
    db_session.add_all([biz_a, biz_b])
    db_session.flush()

    pub_a, sec_a, hash_a = generate_client_keys()
    key_a = ClientApiKey(business_id=biz_a.id, public_key=pub_a, secret_key_hash=hash_a, is_active=True)
    faq_a = KnowledgeItem(business_id=biz_a.id, question="Secret info?", answer="Confidential A", status="approved")

    pub_b, sec_b, hash_b = generate_client_keys()
    key_b = ClientApiKey(business_id=biz_b.id, public_key=pub_b, secret_key_hash=hash_b, is_active=True)

    db_session.add_all([key_a, faq_a, key_b])
    db_session.commit()

    # Login as Tenant B
    res_login_b = client.post("/portal/login", data={"client_secret": sec_b}, follow_redirects=False)
    cookies_b = res_login_b.cookies

    # Tenant B attempts to delete Tenant A's FAQ -> must be rejected (404)
    res_del = client.post(f"/portal/knowledge/{faq_a.id}/delete", cookies=cookies_b)
    assert res_del.status_code == 404

    # Verify FAQ A still exists in DB untouched
    still_exists = db_session.query(KnowledgeItem).filter(KnowledgeItem.id == faq_a.id).first()
    assert still_exists is not None
