import pytest
from app.models.receptionist import Business, KnowledgeItem, Call
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_widget_start_call_and_text_turn(client, db_session):
    biz = Business(name="Apex Medical Clinic")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(business_id=biz.id, public_key=pub, secret_key_hash=sec_hash, allowed_origins=["*"])
    faq = KnowledgeItem(
        business_id=biz.id,
        question="What are your opening hours?",
        answer="We are open Monday to Friday 9am to 5pm.",
        category="hours",
        status="approved"
    )
    db_session.add_all([key, faq])
    db_session.commit()

    # 1. Init Session
    res_session = client.post("/api/v1/widget/session", headers={"X-Client-Key": pub, "Origin": "https://test.com"})
    assert res_session.status_code == 200
    token = res_session.json()["session_token"]

    # 2. Start Call
    res_start = client.post(
        "/api/v1/widget/call/start",
        json={"caller_name": "Web Visitor"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_start.status_code == 200
    data = res_start.json()
    call_id = data["call_id"]
    assert "greeting" in data
    assert len(data["greeting"]) > 5

    # 3. Text Turn
    res_turn = client.post(
        f"/api/v1/widget/call/{call_id}/turn",
        json={"caller_message": "What are your opening hours?"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_turn.status_code == 200
    turn_data = res_turn.json()
    assert "reply_text" in turn_data
    assert "9am to 5pm" in turn_data["reply_text"] or "hours" in turn_data["reply_text"].lower()

    # 4. End Call
    res_end = client.post(
        f"/api/v1/widget/call/{call_id}/end",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_end.status_code == 200
    assert res_end.json()["status"] == "ended"

    # Verify Call in DB marked ended
    call_in_db = db_session.query(Call).filter(Call.id == call_id).first()
    assert call_in_db.outcome == "completed"

def test_widget_call_invalid_session_rejected(client):
    res = client.post(
        "/api/v1/widget/call/start",
        json={},
        headers={"Authorization": "Bearer invalid.token.xyz"}
    )
    assert res.status_code == 401
