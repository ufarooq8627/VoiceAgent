import pytest
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_no_dental_hallucination_on_unknown_query():
    db = SessionLocal()
    tools = ReceptionistTools(db=db, business_id="biz-test", call_id="call-test")
    # Non-dental business: Apex Legal Services
    agent = GeminiReceptionistAgent(business_name="Apex Legal Services", tools=tools)

    # Query out-of-domain / unknown service
    result = agent.process_turn(history=[], caller_message="What services do you provide?")

    response_lower = result.spoken_response.lower()
    # Must NOT mention dental services or teeth
    for forbidden in ["root canal", "dental", "extraction", "crowns", "teeth"]:
        assert forbidden not in response_lower, f"Found forbidden dental hallucination: '{forbidden}' in response: {result.spoken_response}"
    db.close()


from app.models.receptionist import Business, Call, CallbackRequest


def test_callback_uses_dynamic_caller_phone():
    db = SessionLocal()
    biz = Business(id="biz-1", name="Apex Legal", timezone="UTC")
    db.add(biz)
    call = Call(id="call-real", business_id="biz-1", provider_call_id="prov-1", caller_number="+19994443333")
    db.add(call)
    db.commit()

    tools = ReceptionistTools(db=db, business_id="biz-1", call_id="call-real", caller_number="+19994443333")
    agent = GeminiReceptionistAgent(business_name="Apex Legal", tools=tools, caller_number="+19994443333")

    history = [{"role": "agent", "content": "Would you like our team to give you a callback?"}]
    result = agent.process_turn(history=history, caller_message="Yes, please call me back")

    assert "schedule_callback" in result.tools_invoked
    cb = db.query(CallbackRequest).filter(CallbackRequest.call_id == "call-real").first()
    assert cb is not None
    assert cb.callback_number == "+19994443333", f"Expected +19994443333, got {cb.callback_number}"
    assert cb.callback_number != "+15550001111"
    db.close()


def test_callback_prompts_for_number_when_missing():
    db = SessionLocal()
    biz = Business(id="biz-2", name="Apex Legal", timezone="UTC")
    db.add(biz)
    call = Call(id="call-anon", business_id="biz-2", provider_call_id="prov-2", caller_number=None)
    db.add(call)
    db.commit()

    tools = ReceptionistTools(db=db, business_id="biz-2", call_id="call-anon", caller_number=None)
    agent = GeminiReceptionistAgent(business_name="Apex Legal", tools=tools, caller_number=None)

    history = [{"role": "agent", "content": "Would you like our team to give you a callback?"}]
    result = agent.process_turn(history=history, caller_message="Yes, please call me")

    assert "schedule_callback" not in result.tools_invoked
    assert "number" in result.spoken_response.lower() or "contact" in result.spoken_response.lower() or "reach" in result.spoken_response.lower()
    db.close()
