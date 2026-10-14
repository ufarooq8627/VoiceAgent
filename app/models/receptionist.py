import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Boolean, Integer, DateTime, ForeignKey, JSON, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    phone_numbers = relationship("BusinessPhoneNumber", back_populates="business", cascade="all, delete-orphan")
    knowledge_items = relationship("KnowledgeItem", back_populates="business", cascade="all, delete-orphan")
    live_data_sources = relationship("LiveDataSource", back_populates="business", cascade="all, delete-orphan")
    calls = relationship("Call", back_populates="business", cascade="all, delete-orphan")
    unanswered_enquiries = relationship("UnansweredEnquiry", back_populates="business", cascade="all, delete-orphan")
    callback_requests = relationship("CallbackRequest", back_populates="business", cascade="all, delete-orphan")
    owner_notifications = relationship("OwnerNotification", back_populates="business", cascade="all, delete-orphan")


class BusinessPhoneNumber(Base):
    __tablename__ = "business_phone_numbers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="mock", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business = relationship("Business", back_populates="phone_numbers")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="general", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="approved", nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    business = relationship("Business", back_populates="knowledge_items")


class LiveDataSource(Base):
    __tablename__ = "live_data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    freshness_limit_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    business = relationship("Business", back_populates="live_data_sources")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    provider_call_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    outcome: Mapped[str] = mapped_column(String(50), default="in_progress", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)

    business = relationship("Business", back_populates="calls")
    unanswered_enquiries = relationship("UnansweredEnquiry", back_populates="call", cascade="all, delete-orphan")
    callback_requests = relationship("CallbackRequest", back_populates="call", cascade="all, delete-orphan")


class UnansweredEnquiry(Base):
    __tablename__ = "unanswered_enquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    call_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("calls.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    owner_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business = relationship("Business", back_populates="unanswered_enquiries")
    call = relationship("Call", back_populates="unanswered_enquiries")
    callback_requests = relationship("CallbackRequest", back_populates="enquiry")
    owner_notifications = relationship("OwnerNotification", back_populates="enquiry", cascade="all, delete-orphan")


class CallbackRequest(Base):
    __tablename__ = "callback_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), nullable=False, index=True)
    enquiry_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unanswered_enquiries.id"), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    callback_number: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    business = relationship("Business", back_populates="callback_requests")
    call = relationship("Call", back_populates="callback_requests")
    enquiry = relationship("UnansweredEnquiry", back_populates="callback_requests")


class OwnerNotification(Base):
    __tablename__ = "owner_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    enquiry_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unanswered_enquiries.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(50), default="email", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    business = relationship("Business", back_populates="owner_notifications")
    enquiry = relationship("UnansweredEnquiry", back_populates="owner_notifications")
