import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, Call, CallbackRequest, UnansweredEnquiry
from app.routes.portal_auth import get_current_tenant

logger = logging.getLogger("app.portal_leads")
router = APIRouter(prefix="/portal", tags=["Portal Calls and Leads"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/calls", response_class=HTMLResponse)
def list_calls(
    request: Request,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    calls = db.query(Call).filter(
        Call.business_id == tenant.id
    ).order_by(Call.started_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="portal/calls.html",
        context={"tenant": tenant, "calls": calls, "single_call": None}
    )

@router.get("/calls/{call_id}", response_class=HTMLResponse)
def view_call_transcript(
    call_id: str,
    request: Request,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    call = db.query(Call).filter(
        Call.id == call_id,
        Call.business_id == tenant.id
    ).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call transcript not found")

    all_calls = db.query(Call).filter(Call.business_id == tenant.id).order_by(Call.started_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="portal/calls.html",
        context={"tenant": tenant, "calls": all_calls, "single_call": call}
    )

@router.get("/leads", response_class=HTMLResponse)
def list_leads(
    request: Request,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    callbacks = db.query(CallbackRequest).filter(
        CallbackRequest.business_id == tenant.id
    ).order_by(CallbackRequest.created_at.desc()).all()

    unanswered = db.query(UnansweredEnquiry).filter(
        UnansweredEnquiry.business_id == tenant.id
    ).order_by(UnansweredEnquiry.created_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="portal/leads.html",
        context={"tenant": tenant, "callbacks": callbacks, "unanswered": unanswered}
    )

@router.post("/leads/callback/{callback_id}/status")
def update_callback_status(
    callback_id: str,
    status: str = Form(...),
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    cb = db.query(CallbackRequest).filter(
        CallbackRequest.id == callback_id,
        CallbackRequest.business_id == tenant.id
    ).first()
    if not cb:
        raise HTTPException(status_code=404, detail="Callback request not found")

    cb.status = status.strip()
    db.commit()
    return RedirectResponse(url="/portal/leads", status_code=303)
