from sqlalchemy.orm import Session
from app.models import InboundMessage, CandidateEvent, ConversationMessage


class AgentService:
    @staticmethod
    def process_reply(db: Session, message_id: str) -> None:
        msg = db.query(InboundMessage).filter(InboundMessage.id == message_id).first()
        if not msg or msg.processed:
            return

        msg.processed = True
        if msg.candidate_id:
            event = CandidateEvent(
                candidate_id=msg.candidate_id,
                event_type="reply_received",
                actor="system",
                payload={"body": msg.body_text, "note": "LLM agent not active (Phase 1)"},
            )
            db.add(event)

            conv = ConversationMessage(
                candidate_id=msg.candidate_id,
                direction="inbound",
                inbound_id=msg.id,
                summary=f"Candidate replied: {msg.body_text[:100]}",
            )
            db.add(conv)

        db.commit()
