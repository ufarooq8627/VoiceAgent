from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.receptionist import (
    UnansweredEnquiry, CallbackRequest, OwnerNotification, KnowledgeItem
)


class EnquiryService:

    @classmethod
    def log_unanswered(
        cls,
        db: Session,
        business_id: str,
        question: str,
        failure_reason: str,
        call_id: str | None = None,
        intent: str | None = None,
        context_summary: str | None = None
    ) -> UnansweredEnquiry:
        enquiry = UnansweredEnquiry(
            business_id=business_id,
            call_id=call_id,
            question=question.strip(),
            intent=intent,
            context_summary=context_summary,
            failure_reason=failure_reason,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(enquiry)
        db.flush()

        notif = OwnerNotification(
            business_id=business_id,
            enquiry_id=enquiry.id,
            channel="email",
            status="pending",
            attempt_count=0,
        )
        db.add(notif)
        db.commit()
        db.refresh(enquiry)
        return enquiry

    @classmethod
    def create_callback_request(
        cls,
        db: Session,
        business_id: str,
        customer_name: str,
        callback_number: str,
        call_id: str,
        enquiry_id: str | None = None,
        caller_consent: bool = False,
        read_back_confirmed: bool = False
    ) -> tuple[bool, str, CallbackRequest | None]:
        if not caller_consent:
            return False, "Caller consent not given for callback", None
        if not read_back_confirmed:
            return False, "Contact details were not confirmed via read-back", None

        clean_name = customer_name.strip() if customer_name else ""
        clean_phone = callback_number.strip() if callback_number else ""

        if not clean_name or not clean_phone:
            return False, "Customer name and phone number are required", None

        callback = CallbackRequest(
            business_id=business_id,
            call_id=call_id,
            enquiry_id=enquiry_id,
            customer_name=clean_name,
            callback_number=clean_phone,
            consent_at=datetime.now(timezone.utc),
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(callback)
        db.commit()
        db.refresh(callback)
        return True, "Callback request scheduled", callback

    @classmethod
    def resolve_enquiry(
        cls,
        db: Session,
        business_id: str,
        enquiry_id: str,
        owner_answer: str,
        publish_to_kb: bool = False,
        kb_category: str = "general"
    ) -> UnansweredEnquiry | None:
        enquiry = db.query(UnansweredEnquiry).filter_by(
            id=enquiry_id,
            business_id=business_id
        ).first()
        if not enquiry:
            return None

        now = datetime.now(timezone.utc)
        enquiry.owner_answer = owner_answer.strip()
        enquiry.status = "resolved"
        enquiry.resolved_at = now

        if publish_to_kb and enquiry.owner_answer:
            kb_item = KnowledgeItem(
                business_id=business_id,
                question=enquiry.question,
                answer=enquiry.owner_answer,
                category=kb_category,
                source="owner_resolution",
                status="approved",
                valid_from=now,
            )
            db.add(kb_item)

        db.commit()
        db.refresh(enquiry)
        return enquiry
