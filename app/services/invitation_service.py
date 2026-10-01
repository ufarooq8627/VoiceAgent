import hashlib
import secrets
from sqlalchemy.orm import Session

from app.models import Invitation


class InvitationService:
    @staticmethod
    def create_invitation(db: Session, candidate_id: str) -> tuple[Invitation, str]:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        invitation = Invitation(
            candidate_id=candidate_id,
            token_hash=token_hash,
            outcome="pending",
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        return invitation, raw_token

    @staticmethod
    def validate_token(db: Session, raw_token: str) -> Invitation | None:
        if not raw_token or not raw_token.strip():
            return None
        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        return db.query(Invitation).filter(Invitation.token_hash == token_hash).first()
