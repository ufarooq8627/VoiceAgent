from sqlalchemy.orm import Session
from app.services.knowledge_service import KnowledgeService
from app.services.live_data_adapter import LiveDataAdapter
from app.services.enquiry_service import EnquiryService


class ReceptionistTools:

    def __init__(self, db: Session, business_id: str, call_id: str | None = None):
        self.db = db
        self.business_id = business_id
        self.call_id = call_id

    def search_faq(self, query: str) -> dict:
        results = KnowledgeService.search_static(self.db, self.business_id, query)
        return {
            "found": len(results) > 0,
            "count": len(results),
            "results": [
                {
                    "id": r["id"],
                    "question": r["question"],
                    "answer": r["answer"],
                    "category": r["category"],
                }
                for r in results
            ]
        }

    def check_live_data(self, item_name: str, requested_date: str | None = None) -> dict:
        return LiveDataAdapter.get_price_or_availability(
            self.db,
            self.business_id,
            item_key=item_name,
            requested_date=requested_date
        )

    def record_unanswered_question(self, question: str, reason: str) -> dict:
        enquiry = EnquiryService.log_unanswered(
            self.db,
            business_id=self.business_id,
            question=question,
            failure_reason=reason,
            call_id=self.call_id
        )
        return {
            "success": True,
            "enquiry_id": enquiry.id,
            "message": "Enquiry recorded successfully. You may now offer the caller a callback."
        }

    def schedule_callback(
        self,
        customer_name: str,
        phone_number: str,
        confirmed_by_caller: bool,
        enquiry_id: str | None = None
    ) -> dict:
        ok, msg, cb = EnquiryService.create_callback_request(
            self.db,
            business_id=self.business_id,
            customer_name=customer_name,
            callback_number=phone_number,
            call_id=self.call_id or "unassigned",
            enquiry_id=enquiry_id,
            caller_consent=True,
            read_back_confirmed=confirmed_by_caller
        )
        return {
            "success": ok,
            "message": msg,
            "callback_id": cb.id if cb else None
        }
