import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.outbound import (
    OutboundCallAttempt,
    OutboundCampaign,
    OutboundCampaignRecipient,
    OutboundContact,
)
from app.services.outbound_service import (
    add_event,
    assess_contact,
    is_call_window_open,
    next_call_window,
)

logger = logging.getLogger("app.outbound.worker")
ACTIVE_CALL_STATUSES = (
    "SUBMITTING", "SUBMISSION_UNKNOWN", "INITIATED", "RINGING", "ANSWERED", "IN_PROGRESS", "PLAYING"
)


def _daily_count(db: Session, campaign: OutboundCampaign, now: datetime) -> int:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(func.count(OutboundCallAttempt.id)).filter(
        OutboundCallAttempt.campaign_id == campaign.id,
        OutboundCallAttempt.created_at >= midnight,
    ).scalar() or 0


def _active_count(db: Session, campaign: OutboundCampaign) -> int:
    return db.query(func.count(OutboundCallAttempt.id)).filter(
        OutboundCallAttempt.campaign_id == campaign.id,
        OutboundCallAttempt.status.in_(ACTIVE_CALL_STATUSES),
    ).scalar() or 0


def _global_active_count(db: Session) -> int:
    return db.query(func.count(OutboundCallAttempt.id)).filter(
        OutboundCallAttempt.status.in_(ACTIVE_CALL_STATUSES),
    ).scalar() or 0


def _claim_one(db: Session, now: datetime):
    row = (
        db.query(OutboundCampaignRecipient)
        .join(OutboundCampaign, OutboundCampaign.id == OutboundCampaignRecipient.campaign_id)
        .filter(
            OutboundCampaign.status == "RUNNING",
            OutboundCampaignRecipient.status == "QUEUED",
            (OutboundCampaignRecipient.next_attempt_at.is_(None))
            | (OutboundCampaignRecipient.next_attempt_at <= now),
        )
        .order_by(OutboundCampaignRecipient.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if not row:
        return None

    campaign = db.query(OutboundCampaign).filter(OutboundCampaign.id == row.campaign_id).first()
    contact = db.query(OutboundContact).filter(OutboundContact.id == row.contact_id).first()
    if not campaign or not contact or campaign.status != "RUNNING":
        row.status = "BLOCKED"
        row.eligibility_reason = "Campaign or contact is unavailable"
        db.commit()
        return None

    assessment = assess_contact(db, campaign, contact)
    if not assessment.eligible:
        row.status = "SUPPRESSED" if "suppress" in (assessment.reason or "").lower() else "BLOCKED"
        row.eligibility_reason = assessment.reason
        db.commit()
        return None

    if not is_call_window_open(campaign, contact, now):
        row.next_attempt_at = next_call_window(campaign, contact, now)
        db.commit()
        return None

    if _daily_count(db, campaign, now) >= campaign.daily_limit:
        next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        row.next_attempt_at = next_day
        db.commit()
        return None

    if (
        _active_count(db, campaign) >= campaign.max_concurrent_calls
        or _global_active_count(db) >= settings.outbound_max_concurrent_calls
    ):
        row.next_attempt_at = now + timedelta(seconds=15)
        db.commit()
        return None

    if row.attempt_count >= campaign.max_attempts:
        row.status = "COMPLETED"
        row.eligibility_reason = "Maximum call attempts reached"
        db.commit()
        return None

    row.status = "SUBMITTING"
    row.attempt_count += 1
    row.updated_at = now
    attempt = OutboundCallAttempt(
        business_id=campaign.business_id,
        campaign_id=campaign.id,
        recipient_id=row.id,
        contact_id=contact.id,
        attempt_number=row.attempt_count,
        status="SUBMITTING",
    )
    db.add(attempt)
    db.flush()
    add_event(db, attempt, "CALL_SUBMISSION_STARTED")
    db.commit()
    db.refresh(attempt)
    return attempt.id, campaign.id, contact.id


def _public_endpoint(path: str) -> str:
    base = settings.outbound_public_base_url.rstrip("/")
    return f"{base}{path}"


def dispatch_once(session_factory=SessionLocal, client=None) -> bool:
    if not settings.outbound_enabled:
        return False
    if not settings.outbound_public_base_url.startswith("https://"):
        logger.error("Outbound worker stopped: OUTBOUND_PUBLIC_BASE_URL must be HTTPS")
        return False
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.error("Outbound worker stopped: Twilio credentials are missing")
        return False

    with session_factory() as db:
        claimed = _claim_one(db, datetime.now(timezone.utc))
    if not claimed:
        return False

    attempt_id, campaign_id, contact_id = claimed
    try:
        from twilio.rest import Client

        client = client or Client(settings.twilio_account_sid, settings.twilio_auth_token)
    except Exception:
        logger.exception("Could not initialize Twilio client")
        _mark_submission_unknown(session_factory, attempt_id, "TWILIO_CLIENT_INIT")
        return True

    # Recheck campaign state, consent, and suppression immediately before dispatch.
    with session_factory() as db:
        attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
        campaign = db.query(OutboundCampaign).filter(OutboundCampaign.id == campaign_id).first()
        contact = db.query(OutboundContact).filter(OutboundContact.id == contact_id).first()
        if not attempt or not campaign or not contact:
            return False
        if not settings.outbound_enabled or campaign.status != "RUNNING":
            attempt.status = "CANCELLED"
            recipient = db.query(OutboundCampaignRecipient).filter(
                OutboundCampaignRecipient.id == attempt.recipient_id
            ).first()
            if recipient:
                recipient.status = "SUPPRESSED"
                recipient.eligibility_reason = "Campaign paused before provider submission"
            add_event(db, attempt, "CALL_CANCELLED_BEFORE_SUBMISSION")
            db.commit()
            return False
        assessment = assess_contact(db, campaign, contact)
        if not assessment.eligible:
            attempt.status = "SUPPRESSED"
            recipient = db.query(OutboundCampaignRecipient).filter(
                OutboundCampaignRecipient.id == attempt.recipient_id
            ).first()
            if recipient:
                recipient.status = "SUPPRESSED"
                recipient.eligibility_reason = assessment.reason
            add_event(db, attempt, "CALL_BLOCKED_BEFORE_SUBMISSION", {"reason": assessment.reason})
            db.commit()
            return False
        to_number = contact.phone_e164
        from_number = campaign.caller_id

    base = settings.outbound_public_base_url.rstrip("/")
    answer_url = _public_endpoint(f"/api/telephony/twilio/outbound/answer/{attempt_id}")
    status_url = _public_endpoint(f"/api/telephony/twilio/outbound/status/{attempt_id}")
    try:
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=answer_url,
            method="POST",
            machine_detection="DetectMessageEnd",
            machine_detection_timeout=settings.outbound_amd_timeout_seconds,
            async_amd=False,
            status_callback=status_url,
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
    except Exception as exc:
        # A timeout may mean Twilio accepted the call. Never retry blindly.
        _mark_submission_unknown(session_factory, attempt_id, type(exc).__name__)
        return True

    with session_factory() as db:
        attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
        if not attempt:
            return True
        attempt.provider_call_sid = call.sid
        attempt.submitted_at = datetime.now(timezone.utc)
        if attempt.status == "SUBMITTING":
            attempt.status = "INITIATED"
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient and recipient.status == "SUBMITTING":
            recipient.status = "IN_PROGRESS"
        add_event(
            db,
            attempt,
            "CALL_SUBMITTED",
            {"call_sid": call.sid},
            idempotency_key=f"submitted:{attempt.id}:{call.sid}",
        )
        db.commit()
    return True


def _mark_submission_unknown(session_factory, attempt_id: str, failure_code: str) -> None:
    with session_factory() as db:
        attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
        if not attempt:
            return
        attempt.status = "SUBMISSION_UNKNOWN"
        attempt.failure_code = failure_code[:100]
        attempt.failure_message = "Provider submission could not be confirmed; automatic retry disabled"
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient:
            recipient.status = "REVIEW_REQUIRED"
            recipient.eligibility_reason = "Call submission is uncertain; reconcile with Twilio before retrying"
        add_event(db, attempt, "SUBMISSION_UNKNOWN", {"failure_code": failure_code})
        db.commit()


def run_forever() -> None:
    logger.info("Outbound worker started; configured enabled=%s", settings.outbound_enabled)
    last_call_started = 0.0
    while True:
        try:
            with SessionLocal() as db:
                slowest_campaign_rate = db.query(func.min(OutboundCampaign.calls_per_second)).filter(
                    OutboundCampaign.status == "RUNNING"
                ).scalar()
            configured_rate = settings.outbound_calls_per_second
            if slowest_campaign_rate is not None:
                configured_rate = min(configured_rate, slowest_campaign_rate)
            interval = 1.0 / configured_rate if configured_rate > 0 else 60.0
            wait = interval - (time.monotonic() - last_call_started)
            if wait > 0:
                time.sleep(wait)
            submitted = dispatch_once()
            if submitted:
                last_call_started = time.monotonic()
            else:
                time.sleep(max(1, settings.outbound_poll_seconds))
        except KeyboardInterrupt:
            logger.info("Outbound worker stopped")
            return
        except Exception:
            logger.exception("Outbound dispatch loop error")
            time.sleep(max(1, settings.outbound_poll_seconds))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
