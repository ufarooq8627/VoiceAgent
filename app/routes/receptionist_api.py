import asyncio
from starlette.concurrency import run_in_threadpool

_call_locks: dict[str, asyncio.Lock] = {}

def _get_call_lock(call_id: str) -> asyncio.Lock:
    if call_id not in _call_locks:
        _call_locks[call_id] = asyncio.Lock()
    return _call_locks[call_id]
from app.agent.receptionist_agent import get_gemini_client
import uuid
import tempfile
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, BusinessPhoneNumber, Call
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools
from app.config import settings
from app.limiter import limiter
from app.routes.auth import login_required

router = APIRouter(tags=["receptionist"], dependencies=[Depends(login_required)])
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
@limiter.limit("10/minute")
def start_call(request: Request, payload: StartCallRequest, db: Session = Depends(get_db)):
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
@limiter.limit("30/minute")
async def process_turn(request: Request, call_id: str, payload: CallTurnRequest, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    if call.outcome != "in_progress":
        raise HTTPException(status_code=400, detail="Call is not in progress.")

    business = db.query(Business).filter(Business.id == call.business_id).first()
    business_name = business.name if business else "Our Business"
    tools = ReceptionistTools(db=db, business_id=call.business_id, call_id=call.id, caller_number=call.caller_number)
    agent = GeminiReceptionistAgent(business_name=business_name, tools=tools, caller_number=call.caller_number)
    history = list(call.transcript or [])

    turn_result = await run_in_threadpool(
        agent.process_turn,
        history=history,
        caller_message=payload.caller_message,
    )

    async with _get_call_lock(call_id):
        # Expire session cache to read latest committed transcript from DB
        db.expire_all()
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call or call.outcome != "in_progress":
            raise HTTPException(status_code=409, detail="Call has ended or is no longer in progress.")

        new_transcript = list(call.transcript or [])
        new_transcript.append({
            "role": "caller",
            "content": payload.caller_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        agent_entry = {
            "role": "agent",
            "content": turn_result.spoken_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools_called": turn_result.tools_invoked,
        }
        if turn_result.meta:
            agent_entry["meta"] = turn_result.meta
        new_transcript.append(agent_entry)
        call.transcript = new_transcript
        db.commit()

    return {
        "call_id": call.id,
        "reply_text": turn_result.spoken_response,
        "tools_called": turn_result.tools_invoked,
        "actions_taken": turn_result.actions_taken,
        "meta": turn_result.meta,
    }


MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10MB ceiling


@router.post("/api/receptionist/calls/{call_id}/audio-turn")
@limiter.limit("30/minute")
async def process_audio_turn(
    request: Request,
    call_id: str,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Receive audio blob from browser MediaRecorder, transcribe via Gemini multimodal,
    then process through the agent pipeline. This bypasses Chrome Speech API entirely.
    """
    # Fast pre-check if Content-Length header or client size is provided
    if audio.size is not None and audio.size > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large. Maximum allowed size is 10MB.")

    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    if call.outcome != "in_progress":
        raise HTTPException(status_code=400, detail="Call is not in progress.")

    # Read audio bytes
    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large. Maximum allowed size is 10MB.")
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio too short or empty.")

    # Transcribe using Gemini
    transcript_text = await _transcribe_audio_with_gemini(audio_bytes, audio.content_type or "audio/webm")
    if not transcript_text or transcript_text.strip() == "":
        return {
            "call_id": call.id,
            "transcription": "",
            "reply_text": "I could not hear anything on the line. It seems your microphone is silent or muted. Please check your mic and speak clearly.",
            "tools_called": [],
            "actions_taken": [],
            "silence_detected": True,
        }

    # Now process the transcribed text through the normal agent pipeline
    business = db.query(Business).filter(Business.id == call.business_id).first()
    business_name = business.name if business else "Our Business"
    tools = ReceptionistTools(db=db, business_id=call.business_id, call_id=call.id, caller_number=call.caller_number)
    agent = GeminiReceptionistAgent(business_name=business_name, tools=tools, caller_number=call.caller_number)
    history = list(call.transcript or [])

    turn_result = await run_in_threadpool(
        agent.process_turn,
        history=history,
        caller_message=transcript_text.strip(),
    )

    async with _get_call_lock(call_id):
        db.expire_all()
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call or call.outcome != "in_progress":
            raise HTTPException(status_code=409, detail="Call has ended or is no longer in progress.")

        new_transcript = list(call.transcript or [])
        new_transcript.append({
            "role": "caller",
            "content": transcript_text.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "voice_mic",
        })
        agent_entry = {
            "role": "agent",
            "content": turn_result.spoken_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools_called": turn_result.tools_invoked,
        }
        if turn_result.meta:
            agent_entry["meta"] = turn_result.meta
        new_transcript.append(agent_entry)
        call.transcript = new_transcript
        db.commit()

    return {
        "call_id": call.id,
        "transcription": transcript_text.strip(),
        "reply_text": turn_result.spoken_response,
        "tools_called": turn_result.tools_invoked,
        "actions_taken": turn_result.actions_taken,
        "meta": turn_result.meta,
    }


async def _transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str) -> str:
    """Use Gemini multimodal API to transcribe audio bytes to text with anti-hallucination guard."""
    try:
        from google.genai import types

        client = get_gemini_client()
        model_name = settings.llm_model or "gemini-3.5-flash-lite"
        print(f"[Gemini STT] Sending {len(audio_bytes)} bytes ({mime_type}) to {model_name}...")

        response = await run_in_threadpool(
            client.models.generate_content,
            model=model_name,
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Listen carefully to this audio recording.\n"
                                "If there is NO audible human speech (e.g. only silence, breathing, background noise, or clicks), "
                                "reply with exactly: NO_SPEECH\n"
                                "If there is human speech, transcribe the spoken words accurately.\n"
                                "Return ONLY the transcription or NO_SPEECH. No quotes, no markdown, no filler."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": __import__("base64").b64encode(audio_bytes).decode("utf-8"),
                            }
                        },
                    ],
                }
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
            ),
        )
        raw_text = (response.text or "").strip()
        print(f"[Gemini STT Output] Raw: {repr(raw_text)}")

        if not raw_text or "NO_SPEECH" in raw_text.upper():
            return ""

        # Remove surrounding quotes or punctuation artifacts if present
        return raw_text.strip(" '\"\n\r")
    except Exception as e:
        print(f"[Gemini STT Error] {e}")
        return ""


@router.post("/api/receptionist/calls/{call_id}/end")
def end_call(call_id: str, payload: EndCallRequest, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")

    _call_locks.pop(call_id, None)
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