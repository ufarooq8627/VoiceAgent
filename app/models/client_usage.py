import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class ClientUsage(Base):
    __tablename__ = "client_usages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    billing_period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    calls_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minutes_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    business = relationship("Business")
