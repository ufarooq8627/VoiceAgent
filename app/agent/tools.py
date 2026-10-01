from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models import Candidate, ConversationMessage, EmailOutbox, Slot, Invitation
from app.services.state_machine import transition_candidate, CandidateStatus, IllegalTransition
from app.services.slot_service import SlotService
from app.services.email_service import EmailService
from app.config import settings
from app.agent import messages


class AgentTools:
    def __init__(self, db: Session, candidate_id: str):
        self.db = db
        self.candidate_id = candidate_id
        self._candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not self._candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

    def active_offer(self) -> dict[str, str]:
        row = (
            self.db.query(EmailOutbox)
            .filter(
                EmailOutbox.candidate_id == self.candidate_id,
                EmailOutbox.status == "sent",
                EmailOutbox.offered_slots.isnot(None),
            )
            .order_by(EmailOutbox.sent_at.desc())
            .first()
        )
        return dict(row.offered_slots) if (row and row.offered_slots) else {}

    def current_slots(self) -> list[dict]:
        return SlotService.get_available(self.db, self._candidate.job_id)

    def get_open_slots(self) -> list[dict]:
        return self.current_slots()

    def get_candidate_context(self) -> dict:
        first_name = self._candidate.name.split()[0] if self._candidate.name else "Candidate"
        job_title = self._candidate.job.title if self._candidate.job else "Position"

        offer = self.active_offer()
        offered_slots = []
        if offer:
            for label, slot_id in offer.items():
                slot = self.db.query(Slot).filter(Slot.id == slot_id).first()
                if slot:
                    when_str = messages.format_slot_time(slot.start_at_utc, self._candidate.timezone)
                    offered_slots.append({
                        "label": label,
                        "when": when_str,
                        "mode": slot.mode,
                    })
        else:
            for s in self.current_slots():
                offered_slots.append({
                    "label": s["label"],
                    "when": f"{s['date']} {s['start_time']}",
                    "mode": s["mode"],
                })

        limit = getattr(settings, "agent_context_messages", 10)
        recent_msgs = (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.candidate_id == self.candidate_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        recent_msgs.reverse()
        history = [
            {
                "direction": m.direction,
                "summary": (m.summary or "")[:300],
            }
            for m in recent_msgs
        ]

        return {
            "first_name": first_name,
            "name": self._candidate.name,
            "status": self._candidate.status,
            "job_title": job_title,
            "offered_slots": offered_slots,
            "history": history,
        }

    def _close_invitations(self, outcome: str):
        invitations = (
            self.db.query(Invitation)
            .filter(Invitation.candidate_id == self.candidate_id, Invitation.outcome == "pending")
            .all()
        )
        for inv in invitations:
            inv.outcome = outcome
        self.db.flush()

    def send(self, kind: str, content: dict, offered_slots: dict | None = None) -> EmailOutbox:
        outbox = EmailService.enqueue(
            db=self.db,
            candidate_id=self.candidate_id,
            kind=kind,
            to_address=self._candidate.email,
            subject=content["subject"],
            body_html=content["body_html"],
            body_text=content["body_text"],
            offered_slots=offered_slots,
            commit=False,
        )
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="outbound",
            outbox_id=outbox.id,
            summary=f"Agent sent {kind}: {content['subject']}",
        )
        self.db.add(conv)
        self.db.flush()
        return outbox

    def send_email(self, subject: str, body: str) -> None:
        self.send("follow_up", {"subject": subject, "body_text": body, "body_html": f"<p>{body}</p>"})

    def book_slot(self, label: str) -> dict:
        label_clean = label.strip().upper() if label else ""
        offer = self.active_offer()
        slot_id = offer.get(label_clean)
        if slot_id is None and not offer:
            cur = self.current_slots()
            match = next((s for s in cur if s["label"].upper() == label_clean), None)
            if match:
                slot_id = match["id"]

        if slot_id is None:
            return {"success": False, "reason": "unknown_label", "remaining_slots": self.current_slots()}

        ok, result = SlotService.book(
            self.db,
            slot_id,
            self.candidate_id,
            actor="agent",
            commit=False,
            transition=False,
        )
        if not ok:
            return {"success": False, "reason": "slot_taken", "remaining_slots": self.current_slots()}

        try:
            transition_candidate(
                self.db,
                self.candidate_id,
                CandidateStatus.BOOKED,
                actor="agent",
                payload={"slot_id": slot_id, "via": "email"},
                commit=False,
            )
        except IllegalTransition:
            self.db.rollback()
            return {"success": False, "reason": "illegal_state"}

        self._close_invitations("booked")
        slot_obj = result.slot if hasattr(result, "slot") else self.db.query(Slot).get(slot_id)
        self.send("confirmation", messages.confirmation(self._candidate, slot_obj))
        booking_id = result.id if hasattr(result, "id") else str(result)
        return {"success": True, "booking_id": booking_id}

    def mark_declined(self, reason: str) -> None:
        transition_candidate(
            self.db,
            self.candidate_id,
            CandidateStatus.DECLINED,
            actor="agent",
            payload={"reason": reason},
            commit=False,
        )
        self._close_invitations("declined")
        self.send("declined_ack", messages.declined_ack(self._candidate))
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="inbound",
            summary=f"Candidate declined: {reason}",
        )
        self.db.add(conv)
        self.db.flush()

    def escalate_to_recruiter(self, reason: str, notify_candidate: bool = True) -> None:
        transition_candidate(
            self.db,
            self.candidate_id,
            CandidateStatus.NEEDS_RECRUITER,
            actor="agent",
            payload={"reason": reason},
            commit=False,
        )
        if notify_candidate:
            self.send("escalation_ack", messages.escalation_ack(self._candidate))
        conv = ConversationMessage(
            candidate_id=self.candidate_id,
            direction="inbound",
            summary=f"Escalated to recruiter: {reason}",
        )
        self.db.add(conv)
        self.db.flush()

    def outbound_count_last_day(self) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        return (
            self.db.query(EmailOutbox)
            .filter(
                EmailOutbox.candidate_id == self.candidate_id,
                EmailOutbox.created_at >= since,
            )
            .count()
        )

    def clarification_count(self) -> int:
        return (
            self.db.query(EmailOutbox)
            .filter(
                EmailOutbox.candidate_id == self.candidate_id,
                EmailOutbox.kind == "clarification",
            )
            .count()
        )
