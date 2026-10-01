import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    interviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("interviewers.id"), nullable=False)
    start_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="video", nullable=False)
    location_or_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="slots")
    interviewer = relationship("Interviewer", back_populates="slots")
    booking = relationship("Booking", back_populates="slot", uselist=False)
