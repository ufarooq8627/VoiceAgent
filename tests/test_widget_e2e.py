import re
import pytest
from app.models.receptionist import Call

def test_demo_embed_page_renders_with_widget(client):
    res = client.get("/demo/embed")
    assert res.status_code == 200
    assert "Apex Luxury Dental Clinic" in res.text
    assert "voice-widget.js" in res.text
    assert "data-client-key=" in res.text

def test_full_widget_commercial_e2e(client, db_session):
    # 1. Fetch demo page
    res_page = client.get("/demo/embed")
    assert res_page.status_code == 200
    match = re.search(r'data-client-key="([^"]+)"', res_page.text)
    assert match is not None
    pub_key = match.group(1)

    # 2. Handshake session
    res_sess = client.post(
        "/api/v1/widget/session",
        headers={"X-Client-Key": pub_key, "Origin": "http://testserver"}
    )
    assert res_sess.status_code == 200
    token = res_sess.json()["session_token"]

    # 3. Start Call
    res_start = client.post(
        "/api/v1/widget/call/start",
        json={"caller_name": "Valued Patient"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_start.status_code == 200
    call_id = res_start.json()["call_id"]

    # 4. Turn answering FAQ
    res_turn = client.post(
        f"/api/v1/widget/call/{call_id}/turn",
        json={"caller_message": "Where are you located?"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_turn.status_code == 200
    reply = res_turn.json()["reply_text"]
    assert "5th avenue" in reply.lower() or "located" in reply.lower()

    # 5. End Call
    res_end = client.post(
        f"/api/v1/widget/call/{call_id}/end",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_end.status_code == 200

    # Verify Call in DB
    call_db = db_session.query(Call).filter(Call.id == call_id).first()
    assert call_db.outcome == "completed"
    assert len(call_db.transcript) >= 3
