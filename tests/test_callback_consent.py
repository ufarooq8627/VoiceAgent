import pytest
from app.agent.receptionist_agent import GeminiReceptionistAgent, AgentTurnResult
from app.agent.receptionist_tools import ReceptionistTools
from app.models.receptionist import Business, Call, CallbackRequest
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    
    # Fake Gemini client to prevent live network calls during tests
    class FakeModel:
        def generate_content(self, *args, **kwargs):
            class FakeResp:
                text = 'A filling costs between $100 and $250 depending on the material.'
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
    Base.metadata.drop_all(bind=engine)

def test_offer_then_unrelated_enquiry_does_not_book():
    db = SessionLocal()
    biz = Business(id='biz-1', name='Dental Care', timezone='UTC')
    call = Call(id='call-1', business_id='biz-1', provider_call_id='prov-1', caller_number='+15551234567')
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id='biz-1', call_id='call-1', caller_number='+15551234567')
    agent = GeminiReceptionistAgent(business_name='Dental Care', tools=tools, caller_number='+15551234567')

    history = [{
        'role': 'agent',
        'content': 'I have your number as 1-5-5-5-1-2-3-4-5-6-7. Is that correct? Please say yes or no.',
        'meta': {'pending_callback': {'number': '+15551234567'}}
    }]

    # Caller asks an unrelated question containing please
    result = agent.process_turn(history=history, caller_message='Can you please tell me the price of a filling?')

    assert 'schedule_callback' not in result.tools_invoked
    cbs = db.query(CallbackRequest).all()
    assert len(cbs) == 0
    db.close()

def test_offer_then_explicit_yes_books_callback():
    db = SessionLocal()
    biz = Business(id='biz-2', name='Dental Care', timezone='UTC')
    call = Call(id='call-2', business_id='biz-2', provider_call_id='prov-2', caller_number='+15551234567')
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id='biz-2', call_id='call-2', caller_number='+15551234567')
    agent = GeminiReceptionistAgent(business_name='Dental Care', tools=tools, caller_number='+15551234567')

    history = [{
        'role': 'agent',
        'content': 'I have your number as 1-5-5-5-1-2-3-4-5-6-7. Is that correct? Please say yes or no.',
        'meta': {'pending_callback': {'number': '+15551234567'}}
    }]

    result = agent.process_turn(history=history, caller_message='yes')

    assert 'schedule_callback' in result.tools_invoked
    cbs = db.query(CallbackRequest).filter(CallbackRequest.call_id == 'call-2').all()
    assert len(cbs) == 1
    assert cbs[0].callback_number == '+15551234567'
    assert 'confirmed' in result.spoken_response.lower()
    db.close()

def test_yes_with_no_pending_offer_does_not_book():
    db = SessionLocal()
    biz = Business(id='biz-3', name='Dental Care', timezone='UTC')
    call = Call(id='call-3', business_id='biz-3', provider_call_id='prov-3', caller_number='+15551234567')
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id='biz-3', call_id='call-3', caller_number='+15551234567')
    agent = GeminiReceptionistAgent(business_name='Dental Care', tools=tools, caller_number='+15551234567')

    # No pending callback in history
    history = [{'role': 'agent', 'content': 'Hello, how can I help you today?'}]
    result = agent.process_turn(history=history, caller_message='yes')

    assert 'schedule_callback' not in result.tools_invoked
    cbs = db.query(CallbackRequest).all()
    assert len(cbs) == 0
    db.close()

def test_double_confirm_attempt_does_not_book_twice():
    db = SessionLocal()
    biz = Business(id='biz-4', name='Dental Care', timezone='UTC')
    call = Call(id='call-4', business_id='biz-4', provider_call_id='prov-4', caller_number='+15551234567')
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id='biz-4', call_id='call-4', caller_number='+15551234567')
    agent = GeminiReceptionistAgent(business_name='Dental Care', tools=tools, caller_number='+15551234567')

    # First turn confirms
    history = [{
        'role': 'agent',
        'content': 'I have your number as 1-5-5-5-1-2-3-4-5-6-7. Is that correct? Please say yes or no.',
        'meta': {'pending_callback': {'number': '+15551234567'}}
    }]
    res1 = agent.process_turn(history=history, caller_message='yes')
    assert 'schedule_callback' in res1.tools_invoked

    # Second turn with confirmation message in history
    history.append({'role': 'caller', 'content': 'yes'})
    history.append({'role': 'agent', 'content': res1.spoken_response, 'meta': res1.meta})

    res2 = agent.process_turn(history=history, caller_message='yes')
    assert 'schedule_callback' not in res2.tools_invoked
    cbs = db.query(CallbackRequest).all()
    assert len(cbs) == 1  # exactly one booking
    db.close()

def test_no_caller_number_asks_for_number():
    db = SessionLocal()
    biz = Business(id='biz-5', name='Dental Care', timezone='UTC')
    call = Call(id='call-5', business_id='biz-5', provider_call_id='prov-5', caller_number=None)
    db.add_all([biz, call])
    db.commit()

    tools = ReceptionistTools(db=db, business_id='biz-5', call_id='call-5', caller_number=None)
    agent = GeminiReceptionistAgent(business_name='Dental Care', tools=tools, caller_number=None)

    history = [{'role': 'agent', 'content': 'Would you like our team to give you a callback?'}]
    result = agent.process_turn(history=history, caller_message='yes please')

    assert 'schedule_callback' not in result.tools_invoked
    assert any(w in result.spoken_response.lower() for w in ['number', 'contact', 'reach'])
    assert result.meta.get('pending_callback', {}).get('state') == 'awaiting_number'
    db.close()
