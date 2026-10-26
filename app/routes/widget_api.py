import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.receptionist import Business, Call
from app.models.client_api_key import ClientApiKey
from app.services.widget_token_service import mint_widget_session_token, verify_widget_session_token
from app.services.voice_synthesis_service import format_speech_payload
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools
from app.limiter import limiter

logger = logging.getLogger("app.widget_api")
router = APIRouter(prefix="/api/v1/widget", tags=["Web Voice Widget"])

security = HTTPBearer(auto_error=False)

def get_widget_session(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    try:
        return verify_widget_session_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

class SessionInitResponse(BaseModel):
    session_token: str
    business_id: str
    business_name: str
    expires_in: int

@router.post("/session", response_model=SessionInitResponse)
@limiter.limit("30/minute")
def init_widget_session(
    request: Request,
    x_client_key: str = Header(..., alias="X-Client-Key"),
    db: Session = Depends(get_db)
):
    key_entry = db.query(ClientApiKey).filter(
        ClientApiKey.public_key == x_client_key,
        ClientApiKey.is_active == True
    ).first()
    if not key_entry:
        raise HTTPException(status_code=403, detail="Invalid or inactive client public key")

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    allowed = key_entry.allowed_origins or []
    if allowed and "*" not in allowed:
        matched = any(origin.startswith(domain.rstrip("/")) for domain in allowed)
        if not matched:
            raise HTTPException(status_code=403, detail=f"Origin '{origin}' is not whitelisted for this widget")

    business = db.query(Business).filter(Business.id == key_entry.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    client_ip = request.client.host if request.client else "unknown"
    ttl = 900  # 15 minutes
    token = mint_widget_session_token(business.id, origin, client_ip, ttl_seconds=ttl)

    return SessionInitResponse(
        session_token=token,
        business_id=business.id,
        business_name=business.name,
        expires_in=ttl
    )

class StartWidgetCallRequest(BaseModel):
    caller_name: Optional[str] = "Website Visitor"

@router.post("/call/start")
def start_widget_call(
    payload: StartWidgetCallRequest,
    session_data: dict = Depends(get_widget_session),
    db: Session = Depends(get_db)
):
    biz_id = session_data["business_id"]
    business = db.query(Business).filter(Business.id == biz_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    call_id = str(uuid.uuid4())
    greeting = f"Hello! Welcome to {business.name}. How can I assist you today?"
    
    new_call = Call(
        id=call_id,
        business_id=biz_id,
        provider_call_id=f"widget_{call_id[:12]}",
        caller_number="web_caller",
        transcript=[{"role": "agent", "content": greeting, "timestamp": datetime.now(timezone.utc).isoformat()}],
        outcome="in_progress"
    )
    db.add(new_call)
    db.commit()
    
    return {
        "call_id": call_id,
        "greeting": greeting,
        "business_name": business.name
    }

class WidgetTurnRequest(BaseModel):
    caller_message: str

@router.post("/call/{call_id}/turn")
async def widget_text_turn(
    call_id: str,
    payload: WidgetTurnRequest,
    session_data: dict = Depends(get_widget_session),
    db: Session = Depends(get_db)
):
    biz_id = session_data["business_id"]
    call = db.query(Call).filter(Call.id == call_id, Call.business_id == biz_id).first()
    if not call or call.outcome != "in_progress":
        raise HTTPException(status_code=404, detail="Active call not found")

    business = db.query(Business).filter(Business.id == biz_id).first()
    biz_name = business.name if business else "Our Clinic"

    tools = ReceptionistTools(db=db, business_id=biz_id, call_id=call.id, caller_number="web_caller")
    agent = GeminiReceptionistAgent(business_name=biz_name, tools=tools, caller_number="web_caller")

    # Run AI agent turn safely
    agent_result = await run_in_threadpool(agent.process_turn, history=call.transcript or [], caller_message=payload.caller_message)

    current_transcript = list(call.transcript or [])
    current_transcript.append({
        "role": "caller",
        "content": payload.caller_message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    current_transcript.append({
        "role": "agent",
        "content": agent_result.spoken_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": agent_result.meta
    })
    call.transcript = current_transcript
    db.commit()

    return {
        "reply_text": agent_result.spoken_response,
        "speech_text": format_speech_payload(agent_result.spoken_response),
        "action": "reply",
        "tools_invoked": agent_result.tools_invoked,
        "metadata": agent_result.meta
    }

@router.post("/call/{call_id}/end")
def end_widget_call(
    call_id: str,
    session_data: dict = Depends(get_widget_session),
    db: Session = Depends(get_db)
):
    biz_id = session_data["business_id"]
    call = db.query(Call).filter(Call.id == call_id, Call.business_id == biz_id).first()
    if call and call.outcome == "in_progress":
        call.outcome = "completed"
        call.ended_at = datetime.now(timezone.utc)
        db.commit()
    return {"status": "ended"}
