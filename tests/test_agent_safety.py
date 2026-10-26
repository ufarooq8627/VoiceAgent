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
