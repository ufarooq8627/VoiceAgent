import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now():
    return datetime.now(timezone.utc)


class OutboundOptOutNumber(Base):
    __tablename__ = "outbound_opt_out_numbers"
    __table_args__ = (UniqueConstraint("phone_e164", name="uq_outbound_optout_phone"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose_scope: Mapped[str] = mapped_column(String(30), default="marketing", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class OutboundVoicemailAsset(Base):
    __tablename__ = "outbound_voicemail_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    script_text: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class OutboundCampaign(Base):
    __tablename__ = "outbound_campaigns"
    __table_args__ = (
        Index("ix_outbound_campaign_business_status", "business_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)  # informational | marketing
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False)
    caller_id: Mapped[str] = mapped_column(String(20), nullable=False)
    opt_out_number_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_opt_out_numbers.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_voicemail_assets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False, index=True)
    earliest_local_time: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    latest_local_time: Mapped[str] = mapped_column(String(5), default="20:00", nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    calls_per_second: Mapped[float] = mapped_column(Float, default=0.07, nullable=False)
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    dnc_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dnc_review_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class OutboundContact(Base):
    __tablename__ = "outbound_contacts"
    __table_args__ = (
        UniqueConstraint("business_id", "phone_e164", name="uq_outbound_contact_business_phone"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="csv", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class OutboundConsent(Base):
    __tablename__ = "outbound_consents"
    __table_args__ = (
        Index("ix_outbound_consent_lookup", "business_id", "contact_id", "purpose", "seller_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_contacts.id"), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(40), nullable=False)  # signed_written | express
    evidence_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    consent_text_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="csv", nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class OutboundSuppression(Base):
    __tablename__ = "outbound_suppressions"
    __table_args__ = (
        Index("ix_outbound_suppression_lookup", "business_id", "phone_e164", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), default="all", nullable=False)  # all | marketing | informational
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class OutboundCampaignRecipient(Base):
    __tablename__ = "outbound_campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_outbound_campaign_contact"),
        Index("ix_outbound_recipient_queue", "campaign_id", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_campaigns.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_contacts.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    eligibility_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class OutboundCallAttempt(Base):
    __tablename__ = "outbound_call_attempts"
    __table_args__ = (
        UniqueConstraint("provider_call_sid", name="uq_outbound_provider_call_sid"),
        UniqueConstraint("recipient_id", "attempt_number", name="uq_outbound_recipient_attempt"),
        Index("ix_outbound_attempt_status", "business_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_campaigns.id"), nullable=False, index=True)
    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_campaign_recipients.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_contacts.id"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(30), default="twilio", nullable=False)
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="SUBMITTING", nullable=False, index=True)
    answered_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    playback_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class OutboundCallEvent(Base):
    __tablename__ = "outbound_call_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbound_event_idempotency"),
        Index("ix_outbound_event_attempt_created", "attempt_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(36), ForeignKey("outbound_call_attempts.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)