import pytest
from app.models.receptionist import Business
from app.models.client_api_key import ClientApiKey, generate_client_keys

def test_widget_config_endpoint_returns_custom_branding(client, db_session):
    biz = Business(name="Emerald Wellness")
    db_session.add(biz)
    db_session.flush()

    pub, sec, sec_hash = generate_client_keys()
    key = ClientApiKey(
        business_id=biz.id,
        public_key=pub,
        secret_key_hash=sec_hash,
        brand_color="#10b981",
        custom_greeting="Welcome to Emerald Wellness! How may we assist your health journey?",
        widget_position="bottom-left",
        is_active=True
    )
    db_session.add(key)
    db_session.commit()

    # Fetch Config
    res = client.get(f"/api/v1/widget/config?client_key={pub}")
    assert res.status_code == 200
    data = res.json()
    assert data["business_name"] == "Emerald Wellness"
    assert data["brand_color"] == "#10b981"
    assert "Emerald Wellness" in data["greeting"]
    assert data["position"] == "bottom-left"

def test_widget_config_invalid_key_returns_404(client):
    res = client.get("/api/v1/widget/config?client_key=pk_live_fake123")
    assert res.status_code in [403, 404]
