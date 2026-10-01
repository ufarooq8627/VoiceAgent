from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Slot, Booking
from app.services.invitation_service import InvitationService
from app.services.slot_service import SlotService
from app.services.state_machine import transition_candidate, CandidateStatus

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["public"])


@router.get("/i/{token}", response_class=HTMLResponse)
async def public_booking_page(request: Request, token: str, db: Session = Depends(get_db)):
    invitation = InvitationService.validate_token(db, token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid or expired invitation link")

    candidate = invitation.candidate
    job = candidate.job

    if candidate.status == CandidateStatus.BOOKED:
        booking = db.query(Booking).filter(Booking.candidate_id == candidate.id, Booking.status == "confirmed").first()
        slot = booking.slot if booking else None
        return templates.TemplateResponse(
            request=request,
            name="public/booked.html",
            context={"job": job, "slot": slot, "candidate": candidate},
        )

    if candidate.status == CandidateStatus.DECLINED:
        return templates.TemplateResponse(
            request=request,
            name="public/declined.html",
            context={"candidate": candidate},
        )

    if candidate.status == CandidateStatus.NEEDS_RECRUITER:
        return templates.TemplateResponse(
            request=request,
            name="public/declined.html",
            context={"candidate": candidate, "message": "Your request has been escalated to our recruiter. We will reach out shortly."},
        )

    available_slots = SlotService.get_available(db, job.id)

    return templates.TemplateResponse(
        request=request,
        name="public/booking.html",
        context={
            "token": token,
            "candidate": candidate,
            "job": job,
            "available_slots": available_slots,
            "error": None,
        },
    )


@router.post("/i/{token}/book", response_class=HTMLResponse)
async def public_book_slot(
    request: Request,
    token: str,
    slot_id: str = Form(...),
    db: Session = Depends(get_db),
):
    invitation = InvitationService.validate_token(db, token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    candidate = invitation.candidate
    job = candidate.job

    success, result = SlotService.book(db, slot_id=slot_id, candidate_id=candidate.id, actor="candidate")
    if not success:
        available_slots = SlotService.get_available(db, job.id)
        return templates.TemplateResponse(
            request=request,
            name="public/booking.html",
            context={
                "token": token,
                "candidate": candidate,
                "job": job,
                "available_slots": available_slots,
                "error": f"Booking failed: {result}. Please choose another available slot.",
            },
            status_code=400,
        )

    invitation.outcome = "booked"
    db.commit()

    slot = db.query(Slot).filter(Slot.id == slot_id).first()
    return templates.TemplateResponse(
        request=request,
        name="public/booked.html",
        context={"job": job, "slot": slot, "candidate": candidate},
    )


@router.post("/i/{token}/decline", response_class=HTMLResponse)
async def public_decline_interview(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    invitation = InvitationService.validate_token(db, token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    candidate = invitation.candidate
    try:
        transition_candidate(
            db,
            candidate.id,
            CandidateStatus.DECLINED,
            actor="candidate",
            payload={"source": "fallback_page"},
        )
    except Exception:
        pass

    invitation.outcome = "declined"
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="public/declined.html",
        context={"candidate": candidate},
    )


@router.post("/i/{token}/none-work", response_class=HTMLResponse)
async def public_none_work(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    invitation = InvitationService.validate_token(db, token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    candidate = invitation.candidate
    try:
        transition_candidate(
            db,
            candidate.id,
            CandidateStatus.NEEDS_RECRUITER,
            actor="candidate",
            payload={"source": "fallback_page", "reason": "No slots fit schedule"},
        )
    except Exception:
        pass

    invitation.outcome = "escalated"
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="public/declined.html",
        context={"candidate": candidate, "message": "We have notified the recruiting team. They will reach out to schedule an alternative time."},
    )
