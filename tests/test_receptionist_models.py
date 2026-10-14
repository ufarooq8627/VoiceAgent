import pytest
from datetime import datetime, timezone, timedelta
from app.models.receptionist import (
    Business, BusinessPhoneNumber, KnowledgeItem, LiveDataSource,
    Call, UnansweredEnquiry, CallbackRequest, OwnerNotification
)

def test_create_business_and_phone_number(db_session):
    biz = Business(name="Acme Dental Clinic", timezone="Asia/Kolkata")
    db_session.add(biz)
    db_session.commit()
    assert biz.id is not None
    assert len(biz.id) == 36

    phone = BusinessPhoneNumber(
        business_id=biz.id,
        phone_number="+15551234567",
        provider="mock",
        active=True
    )
    db_session.add(phone)
    db_session.commit()
    assert phone.business.name == "Acme Dental Clinic"
    assert len(biz.phone_numbers) == 1

def test_knowledge_item_status_and_validity(db_session):
    biz = Business(name="Dr. Smith Practice", timezone="UTC")
    db_session.add(biz)
    db_session.commit()

    item = KnowledgeItem(
        business_id=biz.id,
        question="What are your opening hours?",
        answer="Monday to Friday, 9am to 5pm.",
        category="hours",
        source="owner_manual",
        status="approved",
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=365)
    )
    db_session.add(item)
    db_session.commit()
    assert item.status == "approved"
    assert item.valid_until is not None

def test_live_data_source_config(db_session):
    biz = Business(name="City Cinema", timezone="America/New_York")
    db_session.add(biz)
    db_session.commit()

    source = LiveDataSource(
        business_id=biz.id,
        source_type="booking_system",
        capabilities={"pricing": True, "inventory": True},
        config_reference="cinema_api_v1",
        active=True,
        freshness_limit_seconds=120
    )
    db_session.add(source)
    db_session.commit()
    assert source.freshness_limit_seconds == 120
    assert source.capabilities["pricing"] is True

def test_call_lifecycle_and_enquiry_link(db_session):
    biz = Business(name="Prime Movers", timezone="UTC")
    db_session.add(biz)
    db_session.commit()

    call = Call(
        business_id=biz.id,
        provider_call_id="call-xyz-123",
        caller_number="+19998887777",
        outcome="unanswered_logged",
        summary="Customer asked about oversized piano moving"
    )
    db_session.add(call)
    db_session.commit()

    enquiry = UnansweredEnquiry(
        business_id=biz.id,
        call_id=call.id,
        question="Do you move grand pianos across states?",
        intent="special_moving",
        failure_reason="service_not_in_kb",
        status="pending"
    )
    db_session.add(enquiry)
    db_session.commit()

    callback = CallbackRequest(
        business_id=biz.id,
        call_id=call.id,
        enquiry_id=enquiry.id,
        customer_name="Alice Johnson",
        callback_number="+19998887777",
        consent_at=datetime.now(timezone.utc),
        status="pending"
    )
    db_session.add(callback)

    notification = OwnerNotification(
        business_id=biz.id,
        enquiry_id=enquiry.id,
        channel="email",
        status="pending"
    )
    db_session.add(notification)
    db_session.commit()

    assert enquiry.call.provider_call_id == "call-xyz-123"
    assert len(call.unanswered_enquiries) == 1
    assert len(call.callback_requests) == 1
    assert callback.enquiry.id == enquiry.id
    assert len(enquiry.owner_notifications) == 1
