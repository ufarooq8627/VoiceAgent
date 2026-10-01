import io
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routes.auth import login_required
from app.models import (
    Job, Candidate, Interviewer, Slot, Booking,
    InboundMessage, ConversationMessage, CandidateEvent
)
from app.services.candidate_service import CandidateService
from app.services.slot_service import SlotService
from app.services.email_service import EmailService
from app.services.invitation_service import InvitationService
from app.services.export_service import ExportService
from app.services.state_machine import transition_candidate, CandidateStatus, IllegalTransition

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin", dependencies=[Depends(login_required)], tags=["admin"])


# -----------------------------------------------------------------------------
# Dashboard & Job Campaign Routes
# -----------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    job_data = []

    for j in jobs:
        total = db.query(Candidate).filter(Candidate.job_id == j.id).count()
        shortlisted = db.query(Candidate).filter(Candidate.job_id == j.id, Candidate.status == CandidateStatus.SHORTLISTED).count()
        invited = db.query(Candidate).filter(Candidate.job_id == j.id, Candidate.status == CandidateStatus.INVITED).count()
        booked = db.query(Candidate).filter(Candidate.job_id == j.id, Candidate.status == CandidateStatus.BOOKED).count()
        open_slots = db.query(Slot).filter(Slot.job_id == j.id, Slot.status == "open").count()

        job_data.append({
            "job": j,
            "counts": {
                "total": total,
                "shortlisted": shortlisted,
                "invited": invited,
                "booked": booked,
            },
            "open_slots_count": open_slots,
        })

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={"jobs": job_data, "active_nav": "jobs"},
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    db: Session = Depends(get_db),
):
    job = Job(title=title, description=description, status="open")
    db.add(job)
    db.commit()
    db.refresh(job)
    return RedirectResponse(url=f"/admin/jobs/{job.id}", status_code=303)


@router.get("/jobs/{id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    id: str,
    tab: str = "candidates",
    status: str | None = None,
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job campaign not found")

    # Counts
    counts = {
        "total": db.query(Candidate).filter(Candidate.job_id == id).count(),
        "new": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.NEW).count(),
        "shortlisted": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.SHORTLISTED).count(),
        "invited": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.INVITED).count(),
        "booked": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.BOOKED).count(),
        "declined": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.DECLINED).count(),
        "needs_recruiter": db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.NEEDS_RECRUITER).count(),
    }
    open_slots_count = db.query(Slot).filter(Slot.job_id == id, Slot.status == "open").count()

    candidates = CandidateService.get_by_job(db, id, page=1, per_page=100, status_filter=status)
    slots = db.query(Slot).filter(Slot.job_id == id).order_by(Slot.start_at_utc.asc()).all()
    interviewers = db.query(Interviewer).order_by(Interviewer.name.asc()).all()
    shortlisted_candidates = db.query(Candidate).filter(Candidate.job_id == id, Candidate.status == CandidateStatus.SHORTLISTED).all()

    logs = (
        db.query(ConversationMessage)
        .join(Candidate, ConversationMessage.candidate_id == Candidate.id)
        .filter(Candidate.job_id == id)
        .order_by(ConversationMessage.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/job_detail.html",
        context={
            "job": job,
            "counts": counts,
            "open_slots_count": open_slots_count,
            "candidates": candidates,
            "slots": slots,
            "interviewers": interviewers,
            "shortlisted_candidates": shortlisted_candidates,
            "logs": logs,
            "active_tab": tab,
            "current_status": status,
            "active_nav": "jobs",
        },
    )


# -----------------------------------------------------------------------------
# Candidate Management & Generation
# -----------------------------------------------------------------------------
@router.post("/jobs/{id}/generate-candidates")
async def generate_mock_candidates(id: str, db: Session = Depends(get_db)):
    CandidateService.generate_mock(db, job_id=id, count=20)
    return RedirectResponse(url=f"/admin/jobs/{id}?tab=candidates", status_code=303)


@router.post("/candidates/{id}/shortlist")
async def shortlist_candidate(
    id: str,
    job_id: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        transition_candidate(db, id, CandidateStatus.SHORTLISTED, actor="recruiter")
    except IllegalTransition:
        pass
    return RedirectResponse(url=f"/admin/jobs/{job_id}?tab=candidates", status_code=303)


@router.post("/candidates/bulk-shortlist")
async def bulk_shortlist(
    job_id: str = Form(...),
    candidate_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    for cid in candidate_ids:
        try:
            transition_candidate(db, cid, CandidateStatus.SHORTLISTED, actor="recruiter")
        except IllegalTransition:
            continue
    return RedirectResponse(url=f"/admin/jobs/{job_id}?tab=candidates", status_code=303)


# -----------------------------------------------------------------------------
# Slot & Interviewer Management
# -----------------------------------------------------------------------------
@router.post("/jobs/{id}/slots")
async def create_slots_for_job(
    id: str,
    interviewer_id: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    duration_minutes: int = Form(30),
    mode: str = Form("video"),
    location_or_link: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # Parse ISO / datetime-local string (format: YYYY-MM-DDTHH:MM)
    dt_start = datetime.fromisoformat(start_at).replace(tzinfo=timezone.utc)
    dt_end = datetime.fromisoformat(end_at).replace(tzinfo=timezone.utc)

    SlotService.create_slots(
        db=db,
        job_id=id,
        interviewer_id=interviewer_id,
        start_at_utc=dt_start,
        end_at_utc=dt_end,
        duration_minutes=duration_minutes,
        mode=mode,
        location_or_link=location_or_link,
    )
    return RedirectResponse(url=f"/admin/jobs/{id}?tab=slots", status_code=303)


@router.post("/slots/{id}/cancel")
async def cancel_slot(
    id: str,
    job_id: str = Form(...),
    db: Session = Depends(get_db),
):
    SlotService.cancel(db, id)
    return RedirectResponse(url=f"/admin/jobs/{job_id}?tab=slots", status_code=303)


@router.get("/interviewers", response_class=HTMLResponse)
async def list_interviewers(request: Request, db: Session = Depends(get_db)):
    interviewers = db.query(Interviewer).order_by(Interviewer.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/interviewers.html",
        context={"interviewers": interviewers, "active_nav": "interviewers"},
    )


@router.post("/interviewers")
async def create_interviewer(
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    iv = Interviewer(name=name, email=email)
    db.add(iv)
    db.commit()
    return RedirectResponse(url="/admin/interviewers", status_code=303)


# -----------------------------------------------------------------------------
# Batch Invitations & Export
# -----------------------------------------------------------------------------
@router.post("/jobs/{id}/send-invitations")
async def send_invitations(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
):
    shortlisted = (
        db.query(Candidate)
        .filter(Candidate.job_id == id, Candidate.status == CandidateStatus.SHORTLISTED)
        .all()
    )
    cids = [c.id for c in shortlisted]
    EmailService.enqueue_invitation_batch(
        db=db,
        job_id=id,
        candidate_ids=cids,
        base_url=str(request.base_url),
    )
    return RedirectResponse(url=f"/admin/jobs/{id}?tab=slots", status_code=303)


@router.get("/jobs/{id}/export")
async def export_job_excel(id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    wb = ExportService.export_job(db, id)
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    filename = f"{job.title.replace(' ', '_')}_candidates.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# -----------------------------------------------------------------------------
# Mock Inbox & Conversations (Task 11)
# -----------------------------------------------------------------------------
@router.get("/mock-inbox", response_class=HTMLResponse)
async def mock_inbox_view(request: Request, db: Session = Depends(get_db)):
    if not settings.mock_inbox:
        raise HTTPException(status_code=403, detail="Mock inbox is disabled in settings")

    candidates = db.query(Candidate).order_by(Candidate.created_at.desc()).limit(100).all()
    recent_messages = db.query(InboundMessage).order_by(InboundMessage.received_at.desc()).limit(20).all()

    return templates.TemplateResponse(
        request=request,
        name="admin/mock_inbox.html",
        context={
            "candidates": candidates,
            "recent_messages": recent_messages,
            "tick_interval": settings.agent_tick_interval_seconds,
            "active_nav": "inbox",
        },
    )


@router.post("/mock-inbox/simulate")
async def mock_inbox_simulate(
    candidate_id: str = Form(...),
    from_address: str = Form(...),
    subject: str = Form("Re: Interview Invitation"),
    body_text: str = Form(...),
    db: Session = Depends(get_db),
):
    if not settings.mock_inbox:
        raise HTTPException(status_code=403, detail="Mock inbox is disabled")

    inbound = InboundMessage(
        candidate_id=candidate_id,
        from_address=from_address,
        subject=subject,
        body_text=body_text,
        processed=False,
    )
    db.add(inbound)
    db.commit()
    return RedirectResponse(url="/admin/mock-inbox", status_code=303)


@router.get("/candidates/{id}/conversations", response_class=HTMLResponse)
async def candidate_conversations(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
):
    cand = db.query(Candidate).filter(Candidate.id == id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")

    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.candidate_id == id)
        .order_by(ConversationMessage.created_at.desc())
        .all()
    )
    events = (
        db.query(CandidateEvent)
        .filter(CandidateEvent.candidate_id == id)
        .order_by(CandidateEvent.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/candidate_conversations.html",
        context={"candidate": cand, "messages": messages, "events": events, "active_nav": "jobs"},
    )
