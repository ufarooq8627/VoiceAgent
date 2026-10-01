from sqlalchemy.orm import Session

from app.models import Candidate, ConversationMessage
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.services.email_service import EmailService


class AgentTools:
    def __init__(self, db: Session, candidate_id: str):
        self.db = db
        self.candidate_id = candidate_id
        self._candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not self._candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

    def get_candidate_context(self) -> dict:
        messages = (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.candidate_id == self.candidate_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        return {
            "candidate_id": self.candidate_id,
            "name": self._candidate.name,
            "email": self._candidate.email,
            "job_id": self._candidate.job_id,
            "job_title": self._candidate.job.title if self._candidate.job else "",
            "status": self._candidate.status,
            "conversation_history": [
                {
                    "direction": m.direction,
                    "summary": m.summary,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }

    def get_open_slots(self) -> list[dict]:
        return SlotService.get_available(self.db, self._candidate.job_id)

    def book_slot(self, slot_label: str) -> dict:
        slots = self.get_open_slots()
        target_slot = next((s for s in slots if s["label"].upper() == slot_label.upper()), None)
        if not target_slot:
            return {
                "success": False,
                "reason": "invalid_label",
                "remaining_slots": self.get_open_slots(),
            }

        success, result = SlotService.book(
            self.db,
            slot_id=target_slot["id"],
            candidate_id=self.candidate_id,
            actor="agent",
        )
        if not success:
            return {
                "success": False,
                "reason": "slot_taken",
                "remaining_slots": self.get_open_slots(),
            }

        return {
            "success": True,
            "booking_id": result.id if hasattr(result, "id") else str(result),
        }

    def send_email(self, subject: str, body: str) -> None:
        outbox = EmailService.enqueue(
            db=self.db,
            candidate_id=self.candidate_id,
            kind="follow_up",
            to_address=self._candidate.email,
            subject=subject,
            body_html=f"<p>{body}</p>",
            body_text=body,
        )
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="outbound",
            outbox_id=outbox.id,
            summary=f"Agent sent follow-up: {subject}",
        )
        self.db.add(conv)
        self.db.commit()

    def mark_declined(self, reason: str) -> None:
        transition_candidate(
            self.db,
            self.candidate_id,
            CandidateStatus.DECLINED,
            actor="agent",
            payload={"reason": reason},
        )
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="inbound",
            summary=f"Candidate declined: {reason}",
        )
        self.db.add(conv)
        self.db.commit()

    def escalate_to_recruiter(self, reason: str) -> None:
        transition_candidate(
            self.db,
            self.candidate_id,
            CandidateStatus.NEEDS_RECRUITER,
            actor="agent",
            payload={"reason": reason},
        )
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="inbound",
            summary=f"Escalated to recruiter: {reason}",
        )
        self.db.add(conv)
        self.db.commit()
