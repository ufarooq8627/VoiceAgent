import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.receptionist import Business, Call
from app.database import Base, get_db
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)

    from app.routes.auth import login_required

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = lambda: True

    # Fake Gemini client with a short sleep to simulate concurrent processing
    class FakeModel:
        def generate_content(self, *args, **kwargs):
            import time
            time.sleep(0.1)
            class FakeResp:
                text = "Thank you for asking."
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeGenaiClient:
        models = FakeModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeGenaiClient())

    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.mark.asyncio
async def test_concurrent_turns_preserve_all_entries():
    db = SessionLocal()
    biz = Business(id="biz-c1", name="Apex Legal", timezone="UTC")
    call = Call(id="call-c1", business_id="biz-c1", provider_call_id="prov-c1", outcome="in_progress")
    db.add_all([biz, call])
    db.commit()
    db.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Launch two turns concurrently
        t1 = client.post("/api/receptionist/calls/call-c1/turn", json={"caller_message": "Question 1"})
        t2 = client.post("/api/receptionist/calls/call-c1/turn", json={"caller_message": "Question 2"})

        res1, res2 = await asyncio.gather(t1, t2)
        assert res1.status_code == 200
        assert res2.status_code == 200

    db = SessionLocal()
    saved_call = db.query(Call).filter(Call.id == "call-c1").first()
    transcript = saved_call.transcript or []
    db.close()

    # Both turns must be present: 2 caller + 2 agent = 4 entries
    assert len(transcript) == 4
    contents = [entry["content"] for entry in transcript]
    assert "Question 1" in contents
    assert "Question 2" in contents


@pytest.mark.asyncio
async def test_turn_on_ended_call_returns_409():
    db = SessionLocal()
    biz = Business(id="biz-c2", name="Apex Legal", timezone="UTC")
    call = Call(id="call-c2", business_id="biz-c2", provider_call_id="prov-c2", outcome="completed")
    db.add_all([biz, call])
    db.commit()
    db.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/receptionist/calls/call-c2/turn", json={"caller_message": "Too late"})
        # 400 or 409 when call is not in progress / ended
        assert res.status_code in (400, 409)
