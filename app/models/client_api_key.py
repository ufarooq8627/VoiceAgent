import uuid
import secrets
import bcrypt
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def generate_client_keys() -> tuple[str, str, str]:
    """Generates (public_key, secret_key, secret_hash)"""
    pub = f"pk_live_{secrets.token_urlsafe(24)}"
    sec = f"sk_live_{secrets.token_urlsafe(32)}"
    sec_hash = bcrypt.hashpw(sec.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
    return pub, sec, sec_hash

def verify_client_secret(plain_secret: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_secret.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False

class ClientApiKey(Base):
    __tablename__ = "client_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    secret_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="Default Web Key")
    allowed_origins: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    business = relationship("Business", back_populates="api_keys")
