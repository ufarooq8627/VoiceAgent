import pytest
from datetime import datetime, timezone
from app.models.receptionist import Business, Call, KnowledgeItem, LiveDataSource, CallbackRequest, UnansweredEnquiry
from app.agent.receptionist_tools import ReceptionistTools
from app.agent.receptionist_agent import GeminiReceptionistAgent, AgentTurnResult


@pytest.fixture
def agent_test_env(db_session):
    biz = Business(name="Apex Car Rentals", timezone="UTC")
    db_session.add(biz)
    db_session.commit()

    # Seed static approved knowledge
    k1 = KnowledgeItem(
        business_id=biz.id,
        question="What is your cancellation policy?",
        answer="Free cancellation up to 24 hours before pickup.",
        category="policy",
        status="approved"
    )
    # Seed live data source
    src = LiveDataSource(
        business_id=biz.id,
        source_type="fleet_inventory",
        capabilities={"pricing": True, "availability": True},
        active=True,
        freshness_limit_seconds=300
    )
    # Seed call
    call = Call(
        business_id=biz.id,
        provider_call_id="call-agent-001",
        caller_number="+18005551234",
        outcome="in_progress"
    )
    db_session.add_all([k1, src, call])
    db_session.commit()

    return biz, call


def test_receptionist_tools_search_and_live(db_session, agent_test_env):
    biz, call = agent_test_env
    tools = ReceptionistTools(db=db_session, business_id=biz.id, call_id=call.id)

    # 1. Search FAQ
    res_faq = tools.search_faq("cancellation policy")
    assert res_faq["found"] is True
    assert "24 hours" in res_faq["results"][0]["answer"]

    # 2. Check live data for known item
    res_live = tools.check_live_data("standard_ticket")
    assert res_live["status"] == "confirmed"
    assert res_live["price"] == 25.0

    # 3. Check live data for unknown item -> unconfirmed
    res_unknown = tools.check_live_data("helicopter_rental")
    assert res_unknown["status"] == "unconfirmed"


def test_receptionist_tools_unanswered_and_callback(db_session, agent_test_env):
    biz, call = agent_test_env
    tools = ReceptionistTools(db=db_session, business_id=biz.id, call_id=call.id)

    # Log unanswered
    res_log = tools.record_unanswered_question(
        question="Do you rent child car seats?",
        reason="accessory_not_found"
    )
    assert res_log["success"] is True
    assert res_log["enquiry_id"] is not None

    # Callback attempt without read-back confirmation
    res_cb_unconfirmed = tools.schedule_callback(
        customer_name="Bob Smith",
        phone_number="+18005551234",
        confirmed_by_caller=False
    )
    assert res_cb_unconfirmed["success"] is False

    # Callback with read-back confirmed
    res_cb_confirmed = tools.schedule_callback(
        customer_name="Bob Smith",
        phone_number="+18005551234",
        confirmed_by_caller=True,
        enquiry_id=res_log["enquiry_id"]
    )
    assert res_cb_confirmed["success"] is True

    db_session.refresh(call)
    assert len(call.callback_requests) == 1
    assert call.callback_requests[0].customer_name == "Bob Smith"


def test_agent_turn_processing_with_mock_tools(db_session, agent_test_env):
    biz, call = agent_test_env
    tools = ReceptionistTools(db=db_session, business_id=biz.id, call_id=call.id)
    agent = GeminiReceptionistAgent(business_name=biz.name, tools=tools)

    # 1. Opening greeting discloses AI
    greeting = agent.get_opening_greeting()
    assert "AI" in greeting or "assistant" in greeting
    assert "Apex Car Rentals" in greeting

    # 2. Turn with FAQ question
    result: AgentTurnResult = agent.process_turn(
        history=[],
        caller_message="Hi, what is your cancellation policy?"
    )
    assert result.spoken_response is not None
    assert "24 hours" in result.spoken_response or "cancellation" in result.spoken_response.lower()
    assert "search_faq" in result.tools_invoked
