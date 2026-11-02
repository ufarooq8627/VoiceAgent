import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.outbound import (
    OutboundCallAttempt,
    OutboundCampaign,
    OutboundCampaignRecipient,
    OutboundContact,
    OutboundOptOutNumber,
    OutboundSuppression,
    OutboundVoicemailAsset,
)
from app.services.outbound_service import (
    normalize_us_phone,
    add_event,
    apply_suppression,
    assess_contact,
)

router = APIRouter(tags=["outbound_telephony"])


def _public_url(request: Request) -> str:
    base = settings.outbound_public_base_url.rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="Outbound public URL is not configured")
    query = request.url.query
    return f"{base}{request.url.path}" + (f"?{query}" if query else "")


async def _validated_form(request: Request) -> dict:
    if not settings.twilio_auth_token:
        raise HTTPException(status_code=503, detail="Twilio webhook validation is not configured")
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing Twilio signature")
    form = await request.form()
    params = {key: value for key, value in form.multi_items()}
    try:
        from twilio.request_validator import RequestValidator

        valid = RequestValidator(settings.twilio_auth_token).validate(
            _public_url(request), params, signature
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Could not validate Twilio signature") from exc
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return params


def _twiml(*children) -> str:
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("Response")
    for tag, attrs, value in children:
        node = SubElement(root, tag, attrs)
        if value:
            node.text = value
    return tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _hangup() -> Response:
    return Response(
        content=_twiml(("Hangup", {}, "")),
        media_type="application/xml",
    )


def _media_signature(asset_id: str, expires: int) -> str:
    message = f"{asset_id}:{expires}".encode("utf-8")
    secret = settings.app_secret_key.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _media_url(asset_id: str) -> str:
    expires = int(time.time()) + 600
    signature = _media_signature(asset_id, expires)
    query = urlencode({"exp": expires, "sig": signature})
    return f"{settings.outbound_public_base_url.rstrip('/')}/api/telephony/twilio/outbound/media/{asset_id}?{query}"


def _safe_asset_path(stored_filename: str) -> Path:
    root = Path(settings.outbound_audio_dir).resolve()
    path = (root / stored_filename).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Audio asset not found")
    return path


@router.get("/api/telephony/twilio/outbound/media/{asset_id}")
def serve_audio_asset(
    asset_id: str,
    exp: int,
    sig: str,
    db: Session = Depends(get_db),
):
    if exp < int(time.time()) or exp > int(time.time()) + 900:
        raise HTTPException(status_code=403, detail="Audio link expired")
    expected = _media_signature(asset_id, exp)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=403, detail="Invalid audio link")
    asset = db.query(OutboundVoicemailAsset).filter(
        OutboundVoicemailAsset.id == asset_id,
        OutboundVoicemailAsset.approval_status == "APPROVED",
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Audio asset not found")
    path = _safe_asset_path(asset.stored_filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(path, media_type=asset.mime_type, headers={"Content-Disposition": "inline"})


@router.post("/api/telephony/twilio/outbound/answer/{attempt_id}")
async def outbound_answer(
    attempt_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    form = await _validated_form(request)
    attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
    if not attempt:
        return _hangup()
    call_sid = form.get("CallSid", "")
    if not call_sid:
        return _hangup()
    if attempt.provider_call_sid and attempt.provider_call_sid != call_sid:
        raise HTTPException(status_code=409, detail="Call SID does not match this attempt")
    if (
        attempt.status in {"PLAYING", "PLAYBACK_COMPLETED", "OPTED_OUT", "SUPPRESSED", "BLOCKED", "CANCELLED", "CALL_ENDED_WITHOUT_PLAYBACK_CONFIRMATION"}
        or attempt.status.startswith("NO_MESSAGE_")
    ):
        # Twilio may retry a webhook when it does not receive the first response.
        # Never replay the recording for the same call attempt.
        return _hangup()
    attempt.provider_call_sid = call_sid
    attempt.answered_at = attempt.answered_at or datetime.now(timezone.utc)
    answered_by = form.get("AnsweredBy", "unknown")
    attempt.answered_by = answered_by

    campaign = db.query(OutboundCampaign).filter(OutboundCampaign.id == attempt.campaign_id).first()
    recipient = db.query(OutboundCampaignRecipient).filter(
        OutboundCampaignRecipient.id == attempt.recipient_id
    ).first()
    contact = db.query(OutboundContact).filter(OutboundContact.id == attempt.contact_id).first()
    if not settings.outbound_enabled or not campaign or not recipient or not contact:
        attempt.status = "BLOCKED"
        add_event(db, attempt, "ANSWER_REJECTED", {"reason": "campaign, recipient, or contact missing"})
        db.commit()
        return _hangup()

    add_event(
        db,
        attempt,
        "AMD_RESULT",
        {
            "answered_by": answered_by,
            "machine_detection_duration": form.get("MachineDetectionDuration"),
            "call_sid": call_sid,
        },
        idempotency_key=f"amd:{call_sid}:{answered_by}",
    )

    if not settings.outbound_enabled or campaign.status != "RUNNING":
        attempt.status = "CANCELLED"
        recipient.status = "SUPPRESSED"
        recipient.eligibility_reason = "Campaign is not running"
        add_event(db, attempt, "CALL_BLOCKED", {"reason": "campaign not running"})
        db.commit()
        return _hangup()

    assessment = assess_contact(db, campaign, contact)
    if not assessment.eligible:
        attempt.status = "SUPPRESSED"
        recipient.status = "SUPPRESSED"
        recipient.eligibility_reason = assessment.reason
        add_event(db, attempt, "CALL_BLOCKED", {"reason": assessment.reason})
        db.commit()
        return _hangup()

    if answered_by != "machine_end_beep":
        attempt.status = "NO_MESSAGE_" + answered_by.upper().replace("-", "_")[:30]
        recipient.status = "COMPLETED"
        recipient.eligibility_reason = f"No message delivered; AMD result: {answered_by}"
        db.commit()
        return _hangup()

    asset = db.query(OutboundVoicemailAsset).filter(
        OutboundVoicemailAsset.id == campaign.asset_id,
        OutboundVoicemailAsset.business_id == campaign.business_id,
        OutboundVoicemailAsset.approval_status == "APPROVED",
    ).first()
    if not asset:
        attempt.status = "BLOCKED"
        recipient.status = "BLOCKED"
        recipient.eligibility_reason = "Approved audio asset is unavailable"
        add_event(db, attempt, "CALL_BLOCKED", {"reason": recipient.eligibility_reason})
        db.commit()
        return _hangup()

    attempt.status = "PLAYING"
    recipient.status = "IN_PROGRESS"
    add_event(db, attempt, "PLAYBACK_STARTED", {"asset_id": asset.id})
    db.commit()

    action_url = (
        f"{settings.outbound_public_base_url.rstrip('/')}"
        f"/api/telephony/twilio/outbound/inline-optout/{attempt.id}"
    )
    gather = (
        "Gather",
        {"input": "dtmf", "numDigits": "1", "timeout": "1", "method": "POST", "action": action_url},
        "",
    )
    # Build the nested Gather/Play document separately to keep all TwiML XML-escaped.
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("Response")
    gather_node = SubElement(
        root,
        "Gather",
        input="dtmf",
        numDigits="1",
        timeout="1",
        method="POST",
        action=action_url,
    )
    play = SubElement(gather_node, "Play")
    play.text = _media_url(asset.id)
    SubElement(root, "Hangup")
    xml = tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return Response(content=xml, media_type="application/xml")


@router.post("/api/telephony/twilio/outbound/inline-optout/{attempt_id}")
async def inline_optout(
    attempt_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    form = await _validated_form(request)
    attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
    if not attempt:
        return _hangup()
    digits = form.get("Digits", "")
    campaign = db.query(OutboundCampaign).filter(OutboundCampaign.id == attempt.campaign_id).first()
    contact = db.query(OutboundContact).filter(OutboundContact.id == attempt.contact_id).first()
    if digits == "1" and campaign and contact:
        apply_suppression(
            db,
            business_id=campaign.business_id,
            phone_e164=contact.phone_e164,
            scope=campaign.purpose,
            reason="USER_OPT_OUT",
            source="in_call_dtmf",
        )
        attempt.status = "OPTED_OUT"
        attempt.ended_at = datetime.now(timezone.utc)
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient:
            recipient.status = "SUPPRESSED"
            recipient.eligibility_reason = "Recipient opted out during the call"
        add_event(db, attempt, "OPT_OUT_RECEIVED", {"method": "dtmf"})
        db.commit()
        xml = _twiml(
            ("Say", {"voice": "Polly.Joanna-Neural"}, "Your opt-out request has been recorded. Goodbye."),
            ("Hangup", {}, ""),
        )
        return Response(content=xml, media_type="application/xml")

    if attempt.status == "PLAYING":
        attempt.status = "PLAYBACK_COMPLETED"
        attempt.playback_completed_at = datetime.now(timezone.utc)
        add_event(db, attempt, "PLAYBACK_COMPLETED")
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient:
            recipient.status = "COMPLETED"
            recipient.eligibility_reason = "Voicemail audio completed"
        db.commit()
    return _hangup()


@router.post("/api/telephony/twilio/outbound/status/{attempt_id}")
async def outbound_status(
    attempt_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    form = await _validated_form(request)
    attempt = db.query(OutboundCallAttempt).filter(OutboundCallAttempt.id == attempt_id).first()
    if not attempt:
        return {"status": "ignored"}
    call_sid = form.get("CallSid", "")
    if attempt.provider_call_sid and call_sid and attempt.provider_call_sid != call_sid:
        raise HTTPException(status_code=409, detail="Call SID does not match this attempt")
    if call_sid:
        attempt.provider_call_sid = call_sid
    call_status = form.get("CallStatus", "unknown").lower()
    safe_payload = {
        "call_sid": call_sid,
        "call_status": call_status,
        "call_duration": form.get("CallDuration"),
    }
    add_event(
        db,
        attempt,
        "STATUS_" + call_status.upper()[:30],
        safe_payload,
        idempotency_key=f"status:{call_sid}:{call_status}:{form.get('CallDuration', '')}",
    )
    terminal_attempt = (
        attempt.status in {"PLAYBACK_COMPLETED", "OPTED_OUT", "SUPPRESSED", "BLOCKED", "CANCELLED"}
        or attempt.status.startswith("NO_MESSAGE_")
    )
    if call_status in {"initiated", "ringing", "in-progress", "answered"}:
        if not terminal_attempt and attempt.status != "PLAYING":
            attempt.status = call_status.upper().replace("-", "_")
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient and recipient.status in {"SUBMITTING", "REVIEW_REQUIRED"}:
            recipient.status = "IN_PROGRESS"
            recipient.eligibility_reason = None
    elif call_status in {"busy", "failed", "no-answer", "canceled"}:
        if not terminal_attempt:
            attempt.status = call_status.upper().replace("-", "_")
        attempt.ended_at = datetime.now(timezone.utc)
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient and recipient.status not in {"SUPPRESSED", "COMPLETED"}:
            recipient.status = "COMPLETED"
            recipient.eligibility_reason = f"Call ended with status {call_status}"
    elif call_status == "completed":
        attempt.ended_at = datetime.now(timezone.utc)
        if not terminal_attempt:
            attempt.status = "CALL_ENDED_WITHOUT_PLAYBACK_CONFIRMATION"
        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.id == attempt.recipient_id
        ).first()
        if recipient and recipient.status not in {"SUPPRESSED", "COMPLETED"}:
            recipient.status = "COMPLETED"
            if attempt.status == "CALL_ENDED_WITHOUT_PLAYBACK_CONFIRMATION":
                recipient.eligibility_reason = "Call ended; playback completion was not confirmed"
        duration = form.get("CallDuration")
        if duration and duration.isdigit():
            attempt.duration_seconds = int(duration)
    db.commit()
    return {"status": "ok", "call_sid": attempt.provider_call_sid}


@router.post("/api/telephony/twilio/outbound/opt-out")
async def opt_out_start(request: Request, db: Session = Depends(get_db)):
    form = await _validated_form(request)
    try:
        called_number = normalize_us_phone(form.get("To", ""))
    except ValueError:
        return _hangup()
    numbers = db.query(OutboundOptOutNumber).filter(
        OutboundOptOutNumber.phone_e164 == called_number,
        OutboundOptOutNumber.active.is_(True),
    ).all()
    if len(numbers) != 1:
        return _hangup()
    number = numbers[0]
    from_number = form.get("From", "")
    action_url = (
        f"{settings.outbound_public_base_url.rstrip('/')}"
        "/api/telephony/twilio/outbound/opt-out/confirm"
    )
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("Response")
    gather = SubElement(root, "Gather", input="dtmf", numDigits="1", timeout="8", method="POST", action=action_url)
    say = SubElement(gather, "Say", voice="Polly.Joanna-Neural")
    say.text = "To stop future calls from this business, press 1."
    SubElement(root, "Hangup")
    xml = tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return Response(content=xml, media_type="application/xml")


@router.post("/api/telephony/twilio/outbound/opt-out/confirm")
async def opt_out_confirm(request: Request, db: Session = Depends(get_db)):
    form = await _validated_form(request)
    try:
        called_number = normalize_us_phone(form.get("To", ""))
    except ValueError:
        return _hangup()
    from_number = form.get("From", "")
    if form.get("Digits") != "1":
        return _hangup()
    number = db.query(OutboundOptOutNumber).filter(
        OutboundOptOutNumber.phone_e164 == called_number,
        OutboundOptOutNumber.active.is_(True),
    ).first()
    if not number:
        return _hangup()
    try:
        normalized = normalize_us_phone(from_number)
    except ValueError:
        return _hangup()
    apply_suppression(
        db,
        business_id=number.business_id,
        phone_e164=normalized,
        scope=number.purpose_scope,
        reason="USER_OPT_OUT",
        source="toll_free_ivr",
    )
    db.commit()
    xml = _twiml(
        ("Say", {"voice": "Polly.Joanna-Neural"}, "Your opt-out request has been recorded. Goodbye."),
        ("Hangup", {}, ""),
    )
    return Response(content=xml, media_type="application/xml")
