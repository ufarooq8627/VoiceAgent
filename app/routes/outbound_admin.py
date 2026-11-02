import csv
import io
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.outbound import (
    OutboundCampaign,
    OutboundCampaignRecipient,
    OutboundConsent,
    OutboundContact,
    OutboundOptOutNumber,
    OutboundVoicemailAsset,
)
from app.models.receptionist import Business, BusinessPhoneNumber
from app.routes.auth import login_required
from app.services.outbound_service import normalize_us_phone, preflight_campaign

router = APIRouter(
    prefix="/admin/outbound",
    dependencies=[Depends(login_required)],
    tags=["outbound_admin"],
)


def _campaign_or_404(db: Session, campaign_id: str) -> OutboundCampaign:
    campaign = db.query(OutboundCampaign).filter(OutboundCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(OutboundCampaign).order_by(OutboundCampaign.created_at.desc()).limit(200).all()
    return [
        {
            "id": item.id,
            "business_id": item.business_id,
            "name": item.name,
            "purpose": item.purpose,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
        }
        for item in campaigns
    ]


@router.post("/opt-out-numbers")
def register_opt_out_number(
    business_id: str = Form(...),
    phone_number: str = Form(...),
    purpose_scope: str = Form("marketing"),
    db: Session = Depends(get_db),
):
    if not db.query(Business.id).filter(Business.id == business_id).first():
        raise HTTPException(status_code=404, detail="Business not found")
    if purpose_scope not in {"all", "marketing", "informational"}:
        raise HTTPException(status_code=400, detail="Invalid opt-out purpose scope")
    try:
        normalized = normalize_us_phone(phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    number = db.query(OutboundOptOutNumber).filter(
        OutboundOptOutNumber.phone_e164 == normalized
    ).first()
    if number:
        if number.business_id != business_id:
            raise HTTPException(status_code=409, detail="This opt-out number belongs to another business")
        number.active = True
        number.purpose_scope = purpose_scope
    else:
        number = OutboundOptOutNumber(
            business_id=business_id,
            phone_e164=normalized,
            purpose_scope=purpose_scope,
        )
        db.add(number)
    db.commit()
    return {
        "id": number.id,
        "business_id": business_id,
        "phone_e164": normalized,
        "purpose_scope": number.purpose_scope,
        "active": True,
    }

@router.post("/assets")
async def upload_audio_asset(
    request: Request,
    business_id: str = Form(...),
    name: str = Form(...),
    script_text: str = Form(...),
    audio_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not db.query(Business.id).filter(Business.id == business_id).first():
        raise HTTPException(status_code=404, detail="Business not found")
    if not name.strip() or not script_text.strip():
        raise HTTPException(status_code=400, detail="Asset name and approved script text are required")
    filename = (audio_file.filename or "").lower()
    extension = Path(filename).suffix
    if extension not in {".mp3", ".wav"}:
        raise HTTPException(status_code=400, detail="Upload an MP3 or WAV audio file")
    content = await audio_file.read(settings.outbound_audio_max_bytes + 1)
    if len(content) > settings.outbound_audio_max_bytes:
        raise HTTPException(status_code=413, detail="Audio file is too large")
    if extension == ".wav" and (len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE"):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid WAV container")
    if extension == ".mp3" and not (content.startswith(b"ID3") or (len(content) > 1 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0)):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid MP3 stream")

    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    stored_filename = f"{uuid.uuid4().hex}{extension}"
    root = Path(settings.outbound_audio_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / stored_filename).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid audio storage path")
    target.write_bytes(content)

    asset = OutboundVoicemailAsset(
        business_id=business_id,
        name=name.strip()[:200],
        script_text=script_text.strip(),
        stored_filename=stored_filename,
        sha256=digest,
        mime_type="audio/mpeg" if extension == ".mp3" else "audio/wav",
        approval_status="PENDING",
    )
    db.add(asset)
    db.commit()
    return {
        "id": asset.id,
        "business_id": asset.business_id,
        "name": asset.name,
        "sha256": asset.sha256,
        "approval_status": asset.approval_status,
    }


@router.post("/assets/{asset_id}/approve")
def approve_audio_asset(
    request: Request,
    asset_id: str,
    review_note: str = Form(...),
    db: Session = Depends(get_db),
):
    asset = db.query(OutboundVoicemailAsset).filter(OutboundVoicemailAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Audio asset not found")
    if len(review_note.strip()) < 10:
        raise HTTPException(status_code=400, detail="Add a review note of at least 10 characters")
    asset.approval_status = "APPROVED"
    asset.approved_by = request.session.get("username", "admin")
    asset.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": asset.id, "approval_status": asset.approval_status, "approved_by": asset.approved_by}


@router.post("/campaigns")
def create_campaign(
    business_id: str = Form(...),
    name: str = Form(...),
    purpose: str = Form(...),
    seller_name: str = Form(...),
    caller_id: str = Form(...),
    opt_out_number_id: str = Form(...),
    asset_id: str = Form(...),
    earliest_local_time: str = Form("08:00"),
    latest_local_time: str = Form("20:00"),
    daily_limit: int = Form(500),
    max_attempts: int = Form(1),
    calls_per_second: float = Form(0.07),
    max_concurrent_calls: int = Form(5),
    db: Session = Depends(get_db),
):
    purpose = purpose.strip().lower()
    if purpose not in {"informational", "marketing"}:
        raise HTTPException(status_code=400, detail="Purpose must be informational or marketing")
    try:
        caller = normalize_us_phone(caller_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", earliest_local_time):
        raise HTTPException(status_code=400, detail="earliest_local_time must be HH:MM")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", latest_local_time):
        raise HTTPException(status_code=400, detail="latest_local_time must be HH:MM")
    if earliest_local_time < "08:00" or latest_local_time > "21:00" or earliest_local_time >= latest_local_time:
        raise HTTPException(status_code=400, detail="Calling window must stay between 08:00 and 21:00 local time and must not cross midnight")
    if max_attempts != 1:
        raise HTTPException(status_code=400, detail="Automatic retries are disabled in this pilot; set max_attempts to 1")
    if not name.strip() or not seller_name.strip():
        raise HTTPException(status_code=400, detail="Campaign name and seller name are required")
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    if not db.query(BusinessPhoneNumber.id).filter(
        BusinessPhoneNumber.business_id == business_id,
        BusinessPhoneNumber.phone_number == caller,
        BusinessPhoneNumber.active.is_(True),
        BusinessPhoneNumber.provider == "twilio",
    ).first():
        raise HTTPException(status_code=400, detail="Caller ID must be an active Twilio number for this business")
    if not db.query(OutboundOptOutNumber.id).filter(
        OutboundOptOutNumber.id == opt_out_number_id,
        OutboundOptOutNumber.business_id == business_id,
        OutboundOptOutNumber.active.is_(True),
        OutboundOptOutNumber.purpose_scope.in_(["all", purpose]),
    ).first():
        raise HTTPException(status_code=400, detail="Opt-out number must be active and belong to this business")
    if not db.query(OutboundVoicemailAsset.id).filter(
        OutboundVoicemailAsset.id == asset_id,
        OutboundVoicemailAsset.business_id == business_id,
        OutboundVoicemailAsset.approval_status == "APPROVED",
    ).first():
        raise HTTPException(status_code=400, detail="Select an approved audio asset belonging to this business")

    campaign = OutboundCampaign(
        business_id=business_id,
        name=name.strip()[:200],
        purpose=purpose,
        seller_name=seller_name.strip()[:255],
        caller_id=caller,
        opt_out_number_id=opt_out_number_id,
        asset_id=asset_id,
        earliest_local_time=earliest_local_time,
        latest_local_time=latest_local_time,
        daily_limit=daily_limit,
        max_attempts=max_attempts,
        calls_per_second=calls_per_second,
        max_concurrent_calls=max_concurrent_calls,
    )
    db.add(campaign)
    db.commit()
    return {"id": campaign.id, "status": campaign.status, "business_id": campaign.business_id}


@router.post("/campaigns/{campaign_id}/contacts/import")
async def import_contacts(
    campaign_id: str,
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Contacts can only be imported into a draft campaign")
    raw = await csv_file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="CSV file is limited to 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    required = {"phone", "timezone", "state", "consent_type", "evidence_reference", "consented_at"}
    headers = {item.strip().lower() for item in (reader.fieldnames or [])}
    if not required.issubset(headers):
        raise HTTPException(
            status_code=400,
            detail={"required_columns": sorted(required), "received_columns": sorted(headers)},
        )

    # Normalize input headers and cap imports before allocating database rows.
    rows = list(reader)
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="A single import is limited to 5,000 rows")

    imported = 0
    duplicates = 0
    errors = []
    for line_number, row in enumerate(rows, start=2):
        normalized_row = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        try:
            phone = normalize_us_phone(normalized_row.get("phone", ""))
        except ValueError as exc:
            errors.append({"row": line_number, "reason": str(exc)})
            continue

        timezone_name = normalized_row.get("timezone", "")
        state_code = normalized_row.get("state", "").upper()
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError):
            timezone_name = ""
        if len(state_code) != 2:
            state_code = ""

        contact = db.query(OutboundContact).filter(
            OutboundContact.business_id == campaign.business_id,
            OutboundContact.phone_e164 == phone,
        ).first()
        if not contact:
            contact = OutboundContact(
                business_id=campaign.business_id,
                name=(normalized_row.get("name") or None),
                phone_e164=phone,
                timezone_name=timezone_name,
                state_code=state_code,
                source="admin_csv",
            )
            db.add(contact)
            db.flush()
        else:
            contact.name = normalized_row.get("name") or contact.name
            contact.timezone_name = timezone_name
            contact.state_code = state_code

        recipient = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.campaign_id == campaign.id,
            OutboundCampaignRecipient.contact_id == contact.id,
        ).first()
        if recipient:
            duplicates += 1
        else:
            recipient = OutboundCampaignRecipient(
                business_id=campaign.business_id,
                campaign_id=campaign.id,
                contact_id=contact.id,
                status="PENDING",
            )
            db.add(recipient)

        evidence = normalized_row.get("evidence_reference", "")
        consent_type = normalized_row.get("consent_type", "").lower()
        consented_at = normalized_row.get("consented_at", "")
        if evidence and consent_type in {"express", "signed_written"} and consented_at:
            try:
                granted_at = _parse_datetime(consented_at)
            except ValueError:
                errors.append({"row": line_number, "reason": "consented_at must be an ISO-8601 timestamp"})
            else:
                existing = db.query(OutboundConsent.id).filter(
                    OutboundConsent.business_id == campaign.business_id,
                    OutboundConsent.contact_id == contact.id,
                    OutboundConsent.phone_e164 == phone,
                    OutboundConsent.seller_name == campaign.seller_name,
                    OutboundConsent.purpose == campaign.purpose,
                    OutboundConsent.evidence_reference == evidence,
                    OutboundConsent.granted_at == granted_at,
                ).first()
                if not existing:
                    db.add(OutboundConsent(
                        business_id=campaign.business_id,
                        contact_id=contact.id,
                        phone_e164=phone,
                        seller_name=campaign.seller_name,
                        purpose=campaign.purpose,
                        consent_type=consent_type,
                        evidence_reference=evidence[:1000],
                        consent_text_version=normalized_row.get("consent_text_version") or None,
                        source="admin_csv",
                        granted_at=granted_at,
                    ))
        else:
            errors.append({"row": line_number, "reason": "Consent type, evidence reference, or timestamp is missing"})
        imported += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Import conflicted with another update; retry the import")
    return {"imported": imported, "duplicate_recipients": duplicates, "row_errors": errors}


@router.post("/campaigns/{campaign_id}/preflight")
def run_preflight(campaign_id: str, db: Session = Depends(get_db)):
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status not in {"DRAFT", "APPROVED"}:
        raise HTTPException(status_code=409, detail="Preflight is available only before a campaign starts")
    return preflight_campaign(db, campaign)


@router.post("/campaigns/{campaign_id}/approve")
def approve_campaign(
    request: Request,
    campaign_id: str,
    compliance_approval: str = Form(...),
    approval_note: str = Form(...),
    dnc_checked_at: str = Form(""),
    dnc_review_reference: str = Form(""),
    db: Session = Depends(get_db),
):
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only draft campaigns can be approved")
    if compliance_approval.strip().lower() != "yes":
        raise HTTPException(status_code=400, detail="Explicit compliance approval is required")
    if len(approval_note.strip()) < 20:
        raise HTTPException(status_code=400, detail="Provide a substantive approval note")
    if campaign.purpose == "marketing":
        if not dnc_checked_at.strip() or not dnc_review_reference.strip():
            raise HTTPException(status_code=400, detail="Marketing approval requires a recent DNC review date and reference")
        try:
            campaign.dnc_checked_at = _parse_datetime(dnc_checked_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="dnc_checked_at must be an ISO-8601 timestamp")
        campaign.dnc_review_reference = dnc_review_reference.strip()[:500]

    summary = preflight_campaign(db, campaign)
    if summary["campaign_error"]:
        raise HTTPException(status_code=400, detail=summary["campaign_error"])
    if summary["ready"] == 0:
        raise HTTPException(status_code=400, detail="No eligible contacts remain after preflight")
    campaign.status = "APPROVED"
    campaign.approval_note = approval_note.strip()
    campaign.approved_by = request.session.get("username", "admin")
    campaign.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": campaign.id, "status": campaign.status, "preflight": summary}


@router.post("/campaigns/{campaign_id}/start")
def start_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
):
    if not settings.outbound_enabled:
        raise HTTPException(status_code=503, detail="Outbound dialing is disabled by configuration")
    if not settings.outbound_public_base_url.startswith("https://"):
        raise HTTPException(status_code=503, detail="A public HTTPS webhook URL is required")
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(status_code=503, detail="Twilio credentials are not configured")
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status == "PAUSED":
        queued_count = db.query(OutboundCampaignRecipient).filter(
            OutboundCampaignRecipient.campaign_id == campaign.id,
            OutboundCampaignRecipient.status == "QUEUED",
        ).count()
        campaign.status = "RUNNING"
        db.commit()
        return {"id": campaign.id, "status": campaign.status, "resumed": True, "queued": queued_count}
    if campaign.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Campaign must be approved or paused before it can start")
    summary = preflight_campaign(db, campaign)
    if summary["campaign_error"]:
        raise HTTPException(status_code=400, detail=summary["campaign_error"])
    ready = db.query(OutboundCampaignRecipient).filter(
        OutboundCampaignRecipient.campaign_id == campaign.id,
        OutboundCampaignRecipient.status == "READY",
    ).all()
    if not ready:
        raise HTTPException(status_code=400, detail="No eligible contacts are ready to call")
    for recipient in ready:
        recipient.status = "QUEUED"
        recipient.next_attempt_at = datetime.now(timezone.utc)
    campaign.status = "RUNNING"
    campaign.started_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": campaign.id, "status": campaign.status, "queued": len(ready)}


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status != "RUNNING":
        raise HTTPException(status_code=409, detail="Only a running campaign can be paused")
    campaign.status = "PAUSED"
    db.commit()
    return {"id": campaign.id, "status": campaign.status}


@router.post("/campaigns/{campaign_id}/stop")
def stop_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = _campaign_or_404(db, campaign_id)
    if campaign.status in {"STOPPED", "COMPLETED"}:
        return {"id": campaign.id, "status": campaign.status}
    campaign.status = "STOPPED"
    pending = db.query(OutboundCampaignRecipient).filter(
        OutboundCampaignRecipient.campaign_id == campaign.id,
        OutboundCampaignRecipient.status.in_(["PENDING", "READY", "QUEUED", "BLOCKED"]),
    ).all()
    for recipient in pending:
        recipient.status = "SUPPRESSED"
        recipient.eligibility_reason = "Campaign stopped by administrator"
    db.commit()
    return {"id": campaign.id, "status": campaign.status, "cancelled_recipients": len(pending)}


@router.post("/suppressions")
def add_suppression(
    request: Request,
    business_id: str = Form(...),
    phone_number: str = Form(...),
    scope: str = Form("all"),
    reason: str = Form("MANUAL_SUPPRESSION"),
    db: Session = Depends(get_db),
):
    if scope not in {"all", "marketing", "informational"}:
        raise HTTPException(status_code=400, detail="Invalid suppression scope")
    if not db.query(Business.id).filter(Business.id == business_id).first():
        raise HTTPException(status_code=404, detail="Business not found")
    try:
        phone = normalize_us_phone(phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.outbound_service import apply_suppression

    item = apply_suppression(
        db,
        business_id=business_id,
        phone_e164=phone,
        scope=scope,
        reason=reason[:50],
        source="admin",
        created_by=request.session.get("username", "admin"),
    )
    db.commit()
    return {"id": item.id, "business_id": business_id, "phone_e164": phone, "scope": item.scope}


@router.get("/campaigns/{campaign_id}")
def campaign_detail(campaign_id: str, db: Session = Depends(get_db)):
    campaign = _campaign_or_404(db, campaign_id)
    recipients = db.query(OutboundCampaignRecipient).filter(
        OutboundCampaignRecipient.campaign_id == campaign.id
    ).all()
    attempts = db.query(OutboundCampaignRecipient.status).filter(
        OutboundCampaignRecipient.campaign_id == campaign.id
    ).all()
    counts = {}
    for (status,) in attempts:
        counts[status] = counts.get(status, 0) + 1
    return {
        "id": campaign.id,
        "business_id": campaign.business_id,
        "name": campaign.name,
        "purpose": campaign.purpose,
        "seller_name": campaign.seller_name,
        "status": campaign.status,
        "recipient_count": len(recipients),
        "recipient_status_counts": counts,
        "approved_by": campaign.approved_by,
        "approved_at": campaign.approved_at.isoformat() if campaign.approved_at else None,
    }
