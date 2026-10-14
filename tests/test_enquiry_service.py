import pytest
from datetime import datetime, timezone
from app.models.receptionist import Business, Call, KnowledgeItem, UnansweredEnquiry, CallbackRequest, OwnerNotification
from app.services.enquiry_service import EnquiryService


@pytest.fixture
def test_setup(db_session):
    biz = Business(name="Sunset Dental", timezone="UTC")
    db_session.add(biz)
    db_session.commit()

    call = Call(
        business_id=biz.id,
        provider_call_id="call-mock-999",
        caller_number="+15554443333",
        outcome="in_progress"
    )
    db_session.add(call)
    db_session.commit()
    return biz, call


def test_log_unanswered_enquiry_creates_notification(db_session, test_setup):
    biz, call = test_setup
    enquiry = EnquiryService.log_unanswered(
        db=db_session,
        business_id=biz.id,
        question="Do you accept Medicare dental vouchers?",
        failure_reason="policy_not_found",
        call_id=call.id,
        intent="insurance_query",
        context_summary="Customer asked about government dental scheme"
    )

    assert enquiry.id is not None
    assert enquiry.status == "pending"
    assert enquiry.business_id == biz.id

    # Verify notification created
    notifs = db_session.query(OwnerNotification).filter_by(enquiry_id=enquiry.id).all()
    assert len(notifs) == 1
    assert notifs[0].status == "pending"


def test_create_callback_request_requires_consent_and_readback(db_session, test_setup):
    biz, call = test_setup
    enquiry = EnquiryService.log_unanswered(
        db=db_session,
        business_id=biz.id,
        question="Can I book Dr. Clark specifically?",
        failure_reason="doctor_availability_unknown",
        call_id=call.id
    )

    # 1. Consent false -> must be rejected
    ok1, reason1, cb1 = EnquiryService.create_callback_request(
        db=db_session,
        business_id=biz.id,
        customer_name="John Doe",
        callback_number="+15554443333",
        call_id=call.id,
        enquiry_id=enquiry.id,
        caller_consent=False,
        read_back_confirmed=True
    )
    assert ok1 is False
    assert cb1 is None

    # 2. Read-back not confirmed -> must be rejected
    ok2, reason2, cb2 = EnquiryService.create_callback_request(
        db=db_session,
        business_id=biz.id,
        customer_name="John Doe",
        callback_number="+15554443333",
        call_id=call.id,
        enquiry_id=enquiry.id,
        caller_consent=True,
        read_back_confirmed=False
    )
    assert ok2 is False
    assert cb2 is None

    # Verify zero callback records created so far
    assert db_session.query(CallbackRequest).count() == 0

    # 3. Both consent and read-back confirmed -> created!
    ok3, reason3, cb3 = EnquiryService.create_callback_request(
        db=db_session,
        business_id=biz.id,
        customer_name="John Doe",
        callback_number="+15554443333",
        call_id=call.id,
        enquiry_id=enquiry.id,
        caller_consent=True,
        read_back_confirmed=True
    )
    assert ok3 is True
    assert cb3 is not None
    assert cb3.customer_name == "John Doe"
    assert db_session.query(CallbackRequest).count() == 1


def test_resolve_enquiry_and_publish_to_kb(db_session, test_setup):
    biz, call = test_setup
    enquiry = EnquiryService.log_unanswered(
        db=db_session,
        business_id=biz.id,
        question="Is wheelchair access available at the back door?",
        failure_reason="facility_details_missing",
        call_id=call.id
    )

    # Resolve and publish to KB
    resolved = EnquiryService.resolve_enquiry(
        db=db_session,
        business_id=biz.id,
        enquiry_id=enquiry.id,
        owner_answer="Yes, ramp and automatic door are located at the rear entrance.",
        publish_to_kb=True,
        kb_category="accessibility"
    )

    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None

    # Verify it published into knowledge_items as approved!
    kb_item = db_session.query(KnowledgeItem).filter_by(
        business_id=biz.id,
        question="Is wheelchair access available at the back door?"
    ).first()
    assert kb_item is not None
    assert kb_item.status == "approved"
    assert "ramp and automatic door" in kb_item.answer
