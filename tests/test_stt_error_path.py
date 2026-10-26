import pytest
import io
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.receptionist import Business, Call
from app.database import Base, get_db
from app.routes.auth import login_required
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = lambda: True

    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.mark.asyncio
async def test_stt_silence_returns_mic_muted_message(monkeypatch):
    class SilenceModel:
        def generate_content(self, *args, **kwargs):
            class FakeResp:
                text = "NO_SPEECH"
            return FakeResp()

    class FakeClient:
        models = SilenceModel()

    monkeypatch.setattr('app.routes.receptionist_api.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-s1", name="Apex Dental", timezone="UTC")
    call = Call(id="call-s1", business_id="biz-s1", provider_call_id="p-s1", outcome="in_progress")
    db.add_all([biz, call])
    db.commit()
    db.close()

    dummy_audio = b"RIFF" + b"\x00" * 200
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/receptionist/calls/call-s1/audio-turn",
            files={"audio": ("test.wav", io.BytesIO(dummy_audio), "audio/wav")}
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("silence_detected") is True
        assert "silent or muted" in data["reply_text"].lower()


@pytest.mark.asyncio
async def test_stt_error_returns_processing_trouble_message(monkeypatch):
    class ErrorModel:
        def generate_content(self, *args, **kwargs):
            raise TimeoutError("Gemini STT API timeout")

    class FakeClient:
        models = ErrorModel()

    monkeypatch.setattr('app.routes.receptionist_api.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-s2", name="Apex Dental", timezone="UTC")
    call = Call(id="call-s2", business_id="biz-s2", provider_call_id="p-s2", outcome="in_progress")
    db.add_all([biz, call])
    db.commit()
    db.close()

    dummy_audio = b"RIFF" + b"\x00" * 200
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/receptionist/calls/call-s2/audio-turn",
            files={"audio": ("test.wav", io.BytesIO(dummy_audio), "audio/wav")}
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("error_detected") is True
        assert "trouble processing" in data["reply_text"].lower()
        # Must NOT claim mic is muted when it was an API error!
        assert "silent or muted" not in data["reply_text"].lower()


@pytest.mark.asyncio
async def test_stt_does_not_log_caller_speech(monkeypatch, capsys):
    class SpeechModel:
        def generate_content(self, *args, **kwargs):
            class FakeResp:
                text = "SECRET_CALLER_SENSITIVE_TEXT"
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = SpeechModel()

    monkeypatch.setattr('app.routes.receptionist_api.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-s3", name="Apex Dental", timezone="UTC")
    call = Call(id="call-s3", business_id="biz-s3", provider_call_id="p-s3", outcome="in_progress")
    db.add_all([biz, call])
    db.commit()
    db.close()

    dummy_audio = b"RIFF" + b"\x00" * 200
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/receptionist/calls/call-s3/audio-turn",
            files={"audio": ("test.wav", io.BytesIO(dummy_audio), "audio/wav")}
        )
        assert res.status_code == 200

    captured = capsys.readouterr()
    assert "SECRET_CALLER_SENSITIVE_TEXT" not in captured.out
    assert "SECRET_CALLER_SENSITIVE_TEXT" not in captured.err
