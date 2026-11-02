import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from phonenumbers import PhoneNumberFormat, region_code_for_number
from sqlalchemy.orm import Session

from app.models.outbound import (
    OutboundCallAttempt,
    OutboundCallEvent,
    OutboundCampaign,
    OutboundCampaignRecipient,
    OutboundConsent,
    OutboundContact,
    OutboundOptOutNumber,
    OutboundSuppression,
    OutboundVoicemailAsset,
)
from app.models.receptionist import Business, BusinessPhoneNumber


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str | None = None


def normalize_us_phone(raw: str) -> str:
    try:
        parsed = phonenumbers.parse((raw or "").strip(), "US")
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number") from exc
    if not phonenumbers.is_valid_number(parsed) or region_code_for_number(parsed) != "US":
        raise ValueError("Only valid US telephone numbers are accepted")
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def _parse_hhmm(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        raise ValueError("Calling window must use HH:MM format")


def _campaign_infrastructure_error(db: Session, campaign: OutboundCampaign) -> str | None:
    if campaign.purpose not in {"informational", "marketing"}:
        return "Campaign purpose must be informational or marketing"
    if not campaign.seller_name.strip():
        return "Seller identity is required"
    if campaign.daily_limit < 1 or campaign.max_attempts < 1:
        return "Daily limit and maximum attempts must be positive"
    if campaign.calls_per_second <= 0 or campaign.max_concurrent_calls < 1:
        return "Pacing and concurrency limits must be positive"
    try:
        start_time = _parse_hhmm(campaign.earliest_local_time)
        end_time = _parse_hhmm(campaign.latest_local_time)
    except ValueError as exc:
        return str(exc)
    if start_time < time(8, 0) or end_time > time(21, 0) or start_time >= end_time:
        return "Calling window must stay between 08:00 and 21:00 local time and must not cross midnight"

    business = db.query(Business).filter(Business.id == campaign.business_id).first()
    if not business:
        return "Business no longer exists"

    caller = db.query(BusinessPhoneNumber).filter(
        BusinessPhoneNumber.business_id == campaign.business_id,
        BusinessPhoneNumber.phone_number == campaign.caller_id,
        BusinessPhoneNumber.active.is_(True),
        BusinessPhoneNumber.provider == "twilio",
    ).first()
    if not caller:
        return "Caller ID must be an active Twilio number registered to this business"

    optout = db.query(OutboundOptOutNumber).filter(
        OutboundOptOutNumber.id == campaign.opt_out_number_id,
        OutboundOptOutNumber.business_id == campaign.business_id,
        OutboundOptOutNumber.active.is_(True),
    ).first()
    if not optout:
        return "An active business opt-out number is required"
    if optout.purpose_scope not in {"all", campaign.purpose}:
        return "Opt-out number scope does not cover this campaign purpose"

    asset = db.query(OutboundVoicemailAsset).filter(
        OutboundVoicemailAsset.id == campaign.asset_id,
        OutboundVoicemailAsset.business_id == campaign.business_id,
        OutboundVoicemailAsset.approval_status == "APPROVED",
    ).first()
    if not asset:
        return "An approved audio asset belonging to this business is required"

    if campaign.purpose == "marketing":
        if not campaign.dnc_checked_at or not campaign.dnc_review_reference:
            return "Marketing campaigns require a documented Do Not Call review"
        checked_at = campaign.dnc_checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        review_age = datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)
        if review_age < timedelta(0):
            return "Do Not Call review date cannot be in the future"
        if review_age > timedelta(days=31):
            return "Do Not Call review is older than 31 days"

    return None


def assess_contact(db: Session, campaign: OutboundCampaign, contact: OutboundContact) -> Eligibility:
    if contact.business_id != campaign.business_id:
        return Eligibility(False, "Contact belongs to a different business")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", contact.phone_e164 or ""):
        return Eligibility(False, "Phone number is not normalized to E.164")
    try:
        parsed = phonenumbers.parse(contact.phone_e164, None)
    except phonenumbers.NumberParseException:
        return Eligibility(False, "Phone number is invalid")
    if region_code_for_number(parsed) != "US" or not phonenumbers.is_valid_number(parsed):
        return Eligibility(False, "Only valid US telephone numbers are accepted")
    if not contact.state_code or len(contact.state_code) != 2:
        return Eligibility(False, "US state is required for campaign review")
    try:
        ZoneInfo(contact.timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        return Eligibility(False, "A valid recipient time zone is required")

    suppression = db.query(OutboundSuppression).filter(
        OutboundSuppression.business_id == campaign.business_id,
        OutboundSuppression.phone_e164 == contact.phone_e164,
        OutboundSuppression.active.is_(True),
        OutboundSuppression.scope.in_(["all", campaign.purpose]),
    ).first()
    if suppression:
        return Eligibility(False, "Number is suppressed for this business or campaign purpose")

    consent_query = db.query(OutboundConsent).filter(
        OutboundConsent.business_id == campaign.business_id,
        OutboundConsent.contact_id == contact.id,
        OutboundConsent.phone_e164 == contact.phone_e164,
        OutboundConsent.seller_name == campaign.seller_name,
        OutboundConsent.purpose == campaign.purpose,
        OutboundConsent.revoked_at.is_(None),
        OutboundConsent.evidence_reference != "",
    )
    consent = consent_query.order_by(OutboundConsent.granted_at.desc()).first()
    if not consent:
        return Eligibility(False, "No active consent evidence for this seller, number, and campaign purpose")
    if campaign.purpose == "marketing" and consent.consent_type != "signed_written":
        return Eligibility(False, "Marketing requires seller-specific signed written consent evidence")
    if campaign.purpose == "informational" and consent.consent_type not in {"express", "signed_written"}:
        return Eligibility(False, "Informational calls require documented express consent")

    return Eligibility(True)


def preflight_campaign(db: Session, campaign: OutboundCampaign) -> dict:
    infrastructure_error = _campaign_infrastructure_error(db, campaign)
    recipients = (
        db.query(OutboundCampaignRecipient)
        .filter(OutboundCampaignRecipient.campaign_id == campaign.id)
        .all()
    )
    counts = {"total": len(recipients), "ready": 0, "blocked": 0, "in_progress": 0, "completed": 0, "suppressed": 0}
    for recipient in recipients:
        if recipient.status == "COMPLETED":
            counts["completed"] += 1
            continue
        if recipient.status == "SUPPRESSED":
            counts["suppressed"] += 1
            continue
        if recipient.status in {"QUEUED", "SUBMITTING", "IN_PROGRESS"}:
            counts["in_progress"] += 1
            continue
        contact = db.query(OutboundContact).filter(OutboundContact.id == recipient.contact_id).first()
        if infrastructure_error:
            assessment = Eligibility(False, infrastructure_error)
        elif not contact:
            assessment = Eligibility(False, "Contact no longer exists")
        else:
            assessment = assess_contact(db, campaign, contact)
        if assessment.eligible:
            recipient.status = "READY"
            recipient.eligibility_reason = None
            counts["ready"] += 1
        else:
            recipient.status = "BLOCKED"
            recipient.eligibility_reason = assessment.reason
            counts["blocked"] += 1
    db.commit()
    return {**counts, "campaign_error": infrastructure_error}


def is_call_window_open(campaign: OutboundCampaign, contact: OutboundContact, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(ZoneInfo(contact.timezone_name))
    start = _parse_hhmm(campaign.earliest_local_time)
    end = _parse_hhmm(campaign.latest_local_time)
    current = local_now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def next_call_window(campaign: OutboundCampaign, contact: OutboundContact, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    zone = ZoneInfo(contact.timezone_name)
    local_now = now.astimezone(zone)
    start = _parse_hhmm(campaign.earliest_local_time)
    local_start = datetime.combine(local_now.date(), start, tzinfo=zone)
    if local_now < local_start:
        return local_start.astimezone(timezone.utc)
    return datetime.combine(local_now.date() + timedelta(days=1), start, tzinfo=zone).astimezone(timezone.utc)


def add_event(
    db: Session,
    attempt: OutboundCallAttempt,
    event_type: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> None:
    safe_payload = payload or {}
    canonical = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), default=str)
    key = idempotency_key or hashlib.sha256(
        f"{attempt.id}:{event_type}:{canonical}".encode("utf-8")
    ).hexdigest()
    existing = db.query(OutboundCallEvent.id).filter(
        OutboundCallEvent.idempotency_key == key
    ).first()
    if existing:
        return
    db.add(OutboundCallEvent(
        business_id=attempt.business_id,
        attempt_id=attempt.id,
        event_type=event_type,
        idempotency_key=key,
        payload=safe_payload,
    ))


def apply_suppression(
    db: Session,
    business_id: str,
    phone_e164: str,
    scope: str,
    reason: str,
    source: str,
    created_by: str | None = None,
) -> OutboundSuppression:
    existing = db.query(OutboundSuppression).filter(
        OutboundSuppression.business_id == business_id,
        OutboundSuppression.phone_e164 == phone_e164,
        OutboundSuppression.active.is_(True),
        OutboundSuppression.scope.in_(["all", scope]),
    ).first()
    if existing:
        return existing
    suppression = OutboundSuppression(
        business_id=business_id,
        phone_e164=phone_e164,
        scope=scope,
        reason=reason,
        source=source,
        created_by=created_by,
    )
    db.add(suppression)
    db.flush()
    pending = db.query(OutboundCampaignRecipient).filter(
        OutboundCampaignRecipient.business_id == business_id,
        OutboundCampaignRecipient.contact_id.in_(
            db.query(OutboundContact.id).filter(
                OutboundContact.business_id == business_id,
                OutboundContact.phone_e164 == phone_e164,
            )
        ),
        OutboundCampaignRecipient.status.in_(["PENDING", "READY", "QUEUED", "BLOCKED"]),
    ).all()
    for recipient in pending:
        campaign = db.query(OutboundCampaign).filter(
            OutboundCampaign.id == recipient.campaign_id
        ).first()
        if scope == "all" or (campaign and campaign.purpose == scope):
            recipient.status = "SUPPRESSED"
            recipient.eligibility_reason = "Number opted out or was manually suppressed"
    return suppression
