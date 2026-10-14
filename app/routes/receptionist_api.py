import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, BusinessPhoneNumber, Call
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools

router = APIRouter(tags=["receptionist"])
templates = Jinja2Templates(directory="app/templates")


class StartCallRequest(BaseModel):
    dialed_number: str
    caller_number: str
    caller_name: Optional[str] = None


class CallTurnRequest(BaseModel):
    caller_message: str


class EndCallRequest(BaseModel):
    summary: Optional[str] = None


@router.post("/api/receptionist/calls/start")
def start_call(payload: StartCallRequest, db: Session = Depends(get_db)):
    phone_entry = (
        db.query(BusinessPhoneNumber)
        .filter(
            BusinessPhoneNumber.phone_number == payload.dialed_number,
            BusinessPhoneNumber.active == True,
        )
        .first()
    )
    if not phone_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Dialed number {payload.dialed_number} is not registered with any active business.",
        )

    business = db.query(Business).filter(Business.id == phone_entry.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Associated business not found.")

    call = Call(
        business_id=business.id,
        provider_call_id=f"mock-{uuid.uuid4()}",
        caller_number=payload.caller_number,
        outcome="in_progress",
        started_at=datetime.now(timezone.utc),
        transcript=[],
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    greeting = f"Hello, thank you for calling {business.name}. I am an AI voice receptionist. How may I help you today?"

    return {
        "call_id": call.id,
        "business_id": business.id,
        "business_name": business.name,
        "greeting": greeting,
        "started_at": call.started_at.isoformat(),
    }


@router.post("/api/receptionist/calls/{call_id}/turn")
def process_turn(call_id: str, payload: CallTurnRequest, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    if call.outcome != "in_progress":
        raise HTTPException(status_code=400, detail="Call is not in progress.")

    business = db.query(Business).filter(Business.id == call.business_id).first()
    business_name = business.name if business else "Our Business"
    tools = ReceptionistTools(db=db, business_id=call.business_id, call_id=call.id)
    agent = GeminiReceptionistAgent(business_name=business_name, tools=tools)
    history = list(call.transcript or [])

    turn_result = agent.process_turn(
        history=history,
        caller_message=payload.caller_message,
    )

    new_transcript = list(call.transcript or [])
    new_transcript.append({
        "role": "caller",
        "content": payload.caller_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    new_transcript.append({
        "role": "agent",
        "content": turn_result.spoken_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_called": turn_result.tools_invoked,
    })
    call.transcript = new_transcript
    db.commit()

    return {
        "call_id": call.id,
        "reply_text": turn_result.spoken_response,
        "tools_called": turn_result.tools_invoked,
        "actions_taken": turn_result.actions_taken,
    }


@router.post("/api/receptionist/calls/{call_id}/end")
def end_call(call_id: str, payload: EndCallRequest, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")

    call.outcome = "completed"
    call.ended_at = datetime.now(timezone.utc)
    if payload.summary:
        call.summary = payload.summary
    elif not call.summary:
        msg_count = len(call.transcript or [])
        call.summary = f"Call completed with {msg_count} messages."

    db.commit()
    return {
        "call_id": call.id,
        "status": "completed",
        "ended_at": call.ended_at.isoformat(),
        "summary": call.summary,
    }


@router.get("/admin/mock-call", response_class=HTMLResponse)
def mock_call_page(request: Request, db: Session = Depends(get_db)):
    businesses = db.query(Business).all()
    phone_numbers = db.query(BusinessPhoneNumber).filter(BusinessPhoneNumber.active == True).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/mock_call.html",
        context={
            "businesses": businesses,
            "phone_numbers": phone_numbers,
            "active_nav": "mock-call",
        },
    )
