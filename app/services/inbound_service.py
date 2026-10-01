from sqlalchemy.orm import Session
from app.models import InboundMessage, Candidate, Invitation, ConversationMessage
from app.services.state_machine import CandidateStatus


class InboundService:
    @staticmethod
    def ingest(
        db: Session,
        from_address: str,
        subject: str | None,
        body_text: str,
        headers: dict[str, str] | None = None,
    ) -> InboundMessage:
        message_id = None
        if headers:
            for k, v in headers.items():
                if k.lower() == "message-id":
                    message_id = str(v).strip()
                    break

        if message_id:
            existing = (
                db.query(InboundMessage)
                .filter(InboundMessage.message_id == message_id)
                .first()
            )
            if existing:
                return existing

        email_clean = from_address.strip().lower()

        # 1. Try matching candidate in INVITED or FOLLOW_UP
        matched_candidates = (
            db.query(Candidate)
            .filter(
                Candidate.email.ilike(email_clean),
                Candidate.status.in_([CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP]),
            )
            .all()
        )

        candidate = None
        if len(matched_candidates) == 1:
            candidate = matched_candidates[0]
        elif len(matched_candidates) > 1:
            cid_list = [c.id for c in matched_candidates]
            latest_inv = (
                db.query(Invitation)
                .filter(Invitation.candidate_id.in_(cid_list))
                .order_by(Invitation.created_at.desc())
                .first()
            )
            if latest_inv:
                candidate = next((c for c in matched_candidates if c.id == latest_inv.candidate_id), None)
            if not candidate:
                candidate = matched_candidates[0]
        else:
            candidate = db.query(Candidate).filter(Candidate.email.ilike(email_clean)).first()

        if not candidate:
            inbound = InboundMessage(
                candidate_id=None,
                from_address=from_address,
                subject=subject,
                body_text=body_text,
                raw_headers=headers,
                message_id=message_id,
                processed=True,
                agent_result={"action": "unmatched"},
            )
            db.add(inbound)
            db.commit()
            db.refresh(inbound)
            return inbound

        inbound = InboundMessage(
            candidate_id=candidate.id,
            from_address=from_address,
            subject=subject,
            body_text=body_text,
            raw_headers=headers,
            message_id=message_id,
            processed=False,
        )
        db.add(inbound)
        db.flush()

        conv = ConversationMessage(
            candidate_id=candidate.id,
            direction="inbound",
            inbound_id=inbound.id,
            summary=f"Candidate replied: {body_text[:100]}",
        )
        db.add(conv)
        db.commit()
        db.refresh(inbound)
        return inbound
