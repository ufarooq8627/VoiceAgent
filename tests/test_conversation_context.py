import pytest
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools
from app.models.receptionist import Business, Call
from app.database import Base
from app.config import settings
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

def test_multi_turn_history_included_in_llm_contents(monkeypatch):
    captured_calls = []

    class CapturingModel:
        def generate_content(self, model=None, contents=None, config=None):
            captured_calls.append({"model": model, "contents": contents, "config": config})
            class FakeResp:
                text = "We are open 10am to 2pm on Saturday."
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = CapturingModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-1", name="Dental Care", timezone="UTC")
    call = Call(id="call-1", business_id="biz-1", provider_call_id="p-1")
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id="biz-1", call_id="call-1")
    agent = GeminiReceptionistAgent(business_name="Dental Care", tools=tools)

    history = [
        {"role": "caller", "content": "What are your opening hours?"},
        {"role": "agent", "content": "We are open Monday to Friday 9 to 5."},
    ]

    res = agent.process_turn(history=history, caller_message="And on Saturday?")

    assert len(captured_calls) == 1
    contents = captured_calls[0]["contents"]
    assert isinstance(contents, list), f"Expected list of Content, got {type(contents)}"
    assert len(contents) == 3

    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "What are your opening hours?"

    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "We are open Monday to Friday 9 to 5."

    assert contents[2].role == "user"
    assert "And on Saturday?" in contents[2].parts[0].text
    assert "Verified Business Knowledge:" in contents[2].parts[0].text

    db.close()


def test_history_bounded_by_agent_context_messages(monkeypatch):
    captured_calls = []

    class CapturingModel:
        def generate_content(self, model=None, contents=None, config=None):
            captured_calls.append({"contents": contents})
            class FakeResp:
                text = "Understood."
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = CapturingModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-2", name="Dental Care", timezone="UTC")
    call = Call(id="call-2", business_id="biz-2", provider_call_id="p-2")
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id="biz-2", call_id="call-2")
    agent = GeminiReceptionistAgent(business_name="Dental Care", tools=tools)

    history = []
    for i in range(15):
        role = "caller" if i % 2 == 0 else "agent"
        history.append({"role": role, "content": f"Message {i}"})

    res = agent.process_turn(history=history, caller_message="Final question?")

    assert len(captured_calls) == 1
    contents = captured_calls[0]["contents"]
    assert len(contents) == 11
    assert contents[0].parts[0].text == "Message 5"

    db.close()


def test_faq_context_only_in_last_turn(monkeypatch):
    captured_calls = []

    class CapturingModel:
        def generate_content(self, model=None, contents=None, config=None):
            captured_calls.append({"contents": contents})
            class FakeResp:
                text = "We have parking in back."
            return FakeResp()

        def embed_content(self, *args, **kwargs):
            class FakeEmbedding:
                values = [0.1] * 10
            class FakeResp:
                embedding = FakeEmbedding()
            return FakeResp()

    class FakeClient:
        models = CapturingModel()

    monkeypatch.setattr('app.agent.receptionist_agent.get_gemini_client', lambda: FakeClient())

    db = SessionLocal()
    biz = Business(id="biz-3", name="Dental Care", timezone="UTC")
    call = Call(id="call-3", business_id="biz-3", provider_call_id="p-3")
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id="biz-3", call_id="call-3")
    agent = GeminiReceptionistAgent(business_name="Dental Care", tools=tools)

    history = [
        {"role": "caller", "content": "Hello"},
        {"role": "agent", "content": "Hi, how can I help?"},
        {"role": "caller", "content": "Do you have parking?"},
        {"role": "agent", "content": "Yes, we have free parking in rear."},
    ]

    res = agent.process_turn(history=history, caller_message="Is it wheelchair accessible?")

    contents = captured_calls[0]["contents"]
    for turn in contents[:-1]:
        for part in turn.parts:
            assert "Verified Business Knowledge:" not in part.text

    assert "Verified Business Knowledge:" in contents[-1].parts[0].text
    assert "Is it wheelchair accessible?" in contents[-1].parts[0].text

    db.close()
