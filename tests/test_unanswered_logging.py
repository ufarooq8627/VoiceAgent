import pytest
import json
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools
from app.models.receptionist import Business, Call, KnowledgeItem, UnansweredEnquiry
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_faq_with_negative_wording_does_not_log_unanswered(monkeypatch):
    db = SessionLocal()
    biz = Business(id="biz-u1", name="Apex Dental", timezone="UTC")
    call = Call(id="call-u1", business_id="biz-u1", provider_call_id="p-u1")
    # FAQ answer legitimately contains "don't have"
    k = KnowledgeItem(
        id="k-park",
        business_id="biz-u1",
        question="Do you have parking?",
        answer="We don't have on-site parking, but there is street parking nearby.",
        category="facility",
        status="approved"
    )
    db.add_all([biz, call, k])
    db.commit()

    class FakeModel:
        def generate_content(self, model=None, contents=None, config=None):
            class FakeResp:
                text = json.dumps({
                    "parts": [
                        {
                            "sub_question": "Do you have parking?",
                            "is_covered": True,
                            "answer": "We don't have on-site parking, but there is street parking nearby.",
                            "faq_id": "k-park"
                        }
                    ]
                })
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = FakeModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    tools = ReceptionistTools(db=db, business_id="biz-u1", call_id="call-u1")
    agent = GeminiReceptionistAgent(business_name="Apex Dental", tools=tools)

    result = agent.process_turn(history=[], caller_message="Do you have parking?")

    assert "record_unanswered_question" not in result.tools_invoked
    logged = db.query(UnansweredEnquiry).all()
    assert len(logged) == 0
    assert "don't have on-site parking" in result.spoken_response
    db.close()


def test_multipart_question_logs_only_unanswered_parts(monkeypatch):
    db = SessionLocal()
    biz = Business(id="biz-u2", name="Apex Dental", timezone="UTC")
    call = Call(id="call-u2", business_id="biz-u2", provider_call_id="p-u2")
    k = KnowledgeItem(
        id="k-hours",
        business_id="biz-u2",
        question="What are your hours?",
        answer="We are open Monday to Friday 9 to 5.",
        category="general",
        status="approved"
    )
    db.add_all([biz, call, k])
    db.commit()

    class FakeModel:
        def generate_content(self, model=None, contents=None, config=None):
            class FakeResp:
                text = json.dumps({
                    "parts": [
                        {
                            "sub_question": "What are your hours?",
                            "is_covered": True,
                            "answer": "We are open Monday to Friday 9 to 5.",
                            "faq_id": "k-hours"
                        },
                        {
                            "sub_question": "Do you offer sedation dentistry?",
                            "is_covered": False,
                            "answer": "",
                            "faq_id": ""
                        }
                    ]
                })
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = FakeModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    tools = ReceptionistTools(db=db, business_id="biz-u2", call_id="call-u2")
    agent = GeminiReceptionistAgent(business_name="Apex Dental", tools=tools)

    result = agent.process_turn(history=[], caller_message="What are your hours and do you offer sedation dentistry?")

    # Answered part is spoken
    assert "Monday to Friday 9 to 5" in result.spoken_response
    # Unanswered part is named
    assert "sedation dentistry" in result.spoken_response.lower()

    # Exactly 1 row logged for the unanswered part
    logged = db.query(UnansweredEnquiry).all()
    assert len(logged) == 1
    assert "sedation dentistry" in logged[0].question.lower()
    db.close()


def test_llm_error_fallback_speaks_neutral_message_not_random_faq(monkeypatch):
    db = SessionLocal()
    biz = Business(id="biz-u3", name="Apex Dental", timezone="UTC")
    call = Call(id="call-u3", business_id="biz-u3", provider_call_id="p-u3")
    # A pre-existing FAQ in database
    k = KnowledgeItem(
        id="k-root",
        business_id="biz-u3",
        question="How much is a root canal?",
        answer="A root canal costs $800.",
        category="pricing",
        status="approved"
    )
    db.add_all([biz, call, k])
    db.commit()

    class FailingModel:
        def generate_content(self, *args, **kwargs):
            raise TimeoutError("LLM API call timed out after 20s")

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = FailingModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    tools = ReceptionistTools(db=db, business_id="biz-u3", call_id="call-u3")
    agent = GeminiReceptionistAgent(business_name="Apex Dental", tools=tools)

    result = agent.process_turn(history=[], caller_message="Do you do teeth whitening?")

    # MUST NOT speak root canal FAQ on error!
    assert "800" not in result.spoken_response
    assert "root canal" not in result.spoken_response.lower()

    # Must speak neutral fallback
    assert "can't look that up right now" in result.spoken_response.lower() or "callback" in result.spoken_response.lower()

    # Must log with llm_error reason
    logged = db.query(UnansweredEnquiry).all()
    assert len(logged) == 1
    assert logged[0].failure_reason == "llm_error"
    db.close()


def test_invalid_faq_id_treated_as_unanswered(monkeypatch):
    db = SessionLocal()
    biz = Business(id="biz-u4", name="Apex Dental", timezone="UTC")
    call = Call(id="call-u4", business_id="biz-u4", provider_call_id="p-u4")
    db.add_all([biz, call])
    db.commit()

    # Gemini hallucinates an answer with a non-existent faq_id
    class HallucinatingModel:
        def generate_content(self, model=None, contents=None, config=None):
            class FakeResp:
                text = json.dumps({
                    "parts": [
                        {
                            "sub_question": "Do you accept Delta Dental?",
                            "is_covered": True,
                            "answer": "Yes we accept Delta Dental PPO.",
                            "faq_id": "hallucinated-id-999"
                        }
                    ]
                })
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = HallucinatingModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    tools = ReceptionistTools(db=db, business_id="biz-u4", call_id="call-u4")
    agent = GeminiReceptionistAgent(business_name="Apex Dental", tools=tools)

    result = agent.process_turn(history=[], caller_message="Do you accept Delta Dental?")

    # Treated as unanswered because faq_id doesn't match approved knowledge
    logged = db.query(UnansweredEnquiry).all()
    assert len(logged) == 1
    assert "Delta Dental" in logged[0].question
    db.close()
