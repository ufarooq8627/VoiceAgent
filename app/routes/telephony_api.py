import logging
from starlette.concurrency import run_in_threadpool
from app.config import settings
logger = logging.getLogger("app.telephony")
"""
Telephony Webhook Routes for Twilio (TwiML) and Telnyx (TeXML).

Architecture:
1. Inbound Call arrives -> Provider sends POST webhook to /api/telephony/twilio/voice or /api/telephony/telnyx/voice
2. Server identifies the business by dialed number (To).
3. Server initializes Call session in database.
4. Server returns XML (<Gather input="speech">).
5. When caller speaks, provider sends speech text to /api/telephony/{provider}/gather.
6. The GeminiReceptionistAgent processes the turn, executes tools (search_faq, record_unanswered_question, etc.).
7. Server responds with next <Say> and <Gather>.
8. When call ends, provider sends status callback to /api/telephony/{provider}/status to mark completed.
"""
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, BusinessPhoneNumber, Call
from app.agent.receptionist_agent import GeminiReceptionistAgent
from app.agent.receptionist_tools import ReceptionistTools

router = APIRouter(prefix="/api/telephony", tags=["Telephony Webhooks"])

def _verify_telephony_token(request: Request):
    """Optional security guard: reject requests if telephony_webhook_token is set and doesn't match."""
    token = getattr(settings, "telephony_webhook_token", "")
    if token:
        provided = request.headers.get("X-Telephony-Token") or request.query_params.get("token")
        if provided != token:
            raise HTTPException(status_code=403, detail="Forbidden: Invalid telephony webhook token.")



def _generate_twiml_response(reply_text: str, action_url: str, is_final: bool = False) -> str:
    """Generate standard TwiML XML for Twilio."""
    response_el = ET.Element("Response")
    if is_final:
        say_el = ET.SubElement(response_el, "Say", voice="Polly.Joanna-Neural")
        say_el.text = reply_text
        ET.SubElement(response_el, "Hangup")
    else:
        gather_el = ET.SubElement(
            response_el,
            "Gather",
            input="speech",
            action=action_url,
            method="POST",
            speechTimeout="auto",
            timeout="5",
        )
        say_el = ET.SubElement(gather_el, "Say", voice="Polly.Joanna-Neural")
        say_el.text = reply_text
        fallback_say = ET.SubElement(response_el, "Say", voice="Polly.Joanna-Neural")
        fallback_say.text = "I didn't hear anything. If you need assistance, please call us back. Goodbye!"
        ET.SubElement(response_el, "Hangup")

    return ET.tostring(response_el, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _generate_texml_response(reply_text: str, action_url: str, is_final: bool = False) -> str:
    """Generate standard TeXML for Telnyx (compatible with TwiML schema)."""
    response_el = ET.Element("Response")
    if is_final:
        say_el = ET.SubElement(response_el, "Say", voice="female")
        say_el.text = reply_text
        ET.SubElement(response_el, "Hangup")
    else:
        gather_el = ET.SubElement(
            response_el,
            "Gather",
            input="speech",
            action=action_url,
            method="POST",
            timeout="5",
        )
        say_el = ET.SubElement(gather_el, "Say", voice="female")
        say_el.text = reply_text
        fallback_say = ET.SubElement(response_el, "Say", voice="female")
        fallback_say.text = "Thank you for calling. Have a great day!"
        ET.SubElement(response_el, "Hangup")

    return ET.tostring(response_el, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ---------------------------------------------------------------------------
# 1. TWILIO WEBHOOKS
# ---------------------------------------------------------------------------

@router.post("/twilio/voice")
async def twilio_inbound_voice(
    CallSid: str = Form(...),
    From: str = Form(default=""),
    To: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """
    Twilio calls this webhook when a phone number receives an inbound call.
    Configured in Twilio Console under 'A Call Comes In' -> Webhook POST.
    """
    phone_rec = db.query(BusinessPhoneNumber).filter(
        BusinessPhoneNumber.phone_number == To,
        BusinessPhoneNumber.active == True,
    ).first()

    business = phone_rec.business if phone_rec else db.query(Business).first()
    if not business:
        twiml = _generate_twiml_response(
            "This business is not currently configured to take automated calls. Goodbye.",
            action_url="",
            is_final=True,
        )
        return Response(content=twiml, media_type="application/xml")

    call = db.query(Call).filter(Call.provider_call_id == CallSid).first()
    greeting = f"Hello, thank you for calling {business.name}. I am an AI voice receptionist. How may I help you today?"
    if not call:
        call = Call(
            business_id=business.id,
            provider_call_id=CallSid,
            caller_number=From,
            outcome="in_progress",
            transcript=[
                {
                    "role": "agent",
                    "content": greeting,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "twilio_inbound",
                }
            ],
        )
        db.add(call)
        db.commit()

    gather_url = f"/api/telephony/twilio/gather?call_sid={CallSid}"
    twiml = _generate_twiml_response(greeting, action_url=gather_url)
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/gather")
async def twilio_voice_gather(
    call_sid: str,
    SpeechResult: str = Form(default=""),
    Confidence: float = Form(default=0.0),
    db: Session = Depends(get_db),
):
    """
    Twilio posts speech transcription back to this webhook after caller speaks.
    """
    call = db.query(Call).filter(Call.provider_call_id == call_sid).first()
    if not call or call.outcome != "in_progress":
        twiml = _generate_twiml_response("Thank you for calling. Goodbye.", action_url="", is_final=True)
        return Response(content=twiml, media_type="application/xml")

    user_text = SpeechResult.strip()
    if not user_text:
        gather_url = f"/api/telephony/twilio/gather?call_sid={call_sid}"
        twiml = _generate_twiml_response("I could not hear what you said. Could you please repeat that?", action_url=gather_url)
        return Response(content=twiml, media_type="application/xml")

    business = db.query(Business).filter(Business.id == call.business_id).first()
    business_name = business.name if business else "Our Business"
    tools = ReceptionistTools(db=db, business_id=call.business_id, call_id=call.id)
    agent = GeminiReceptionistAgent(business_name=business_name, tools=tools)

    history = list(call.transcript or [])
    try:
        turn_result = await run_in_threadpool(
            agent.process_turn,
            history=history,
            caller_message=user_text,
        )
    except Exception as exc:
        logger.error(f"[Twilio Voice Gather Error] {exc}", exc_info=True)
        gather_url = f"/api/telephony/twilio/gather?call_sid={call_sid}"
        fallback_msg = "I am having a brief moment processing that. Could you please repeat your question?"
        twiml = _generate_twiml_response(fallback_msg, action_url=gather_url)
        return Response(content=twiml, media_type="application/xml")

    new_transcript = list(call.transcript or [])
    new_transcript.append({
        "role": "caller",
        "content": user_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "twilio_speech",
        "confidence": Confidence,
    })
    new_transcript.append({
        "role": "agent",
        "content": turn_result.spoken_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_called": turn_result.tools_invoked,
    })
    call.transcript = new_transcript
    db.commit()

    is_farewell = any(w in user_text.lower() for w in ["bye", "goodbye", "that is all", "that's all", "hang up", "no thank you"])
    gather_url = f"/api/telephony/twilio/gather?call_sid={call_sid}"
    twiml = _generate_twiml_response(turn_result.spoken_response, action_url=gather_url, is_final=is_farewell)
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/status")
async def twilio_call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(default="completed"),
    CallDuration: str = Form(default="0"),
    db: Session = Depends(get_db),
):
    """
    Twilio status callback when call terminates.
    """
    call = db.query(Call).filter(Call.provider_call_id == CallSid).first()
    if call:
        call.outcome = CallStatus
        call.ended_at = datetime.now(timezone.utc)
        msg_count = len(call.transcript or [])
        call.summary = f"Twilio call ended with status '{CallStatus}'. Duration: {CallDuration}s. Turns: {msg_count}."
        db.commit()
    return {"status": "ok", "call_sid": CallSid}


# ---------------------------------------------------------------------------
# 2. TELNYX WEBHOOKS (TeXML)
# ---------------------------------------------------------------------------

@router.post("/telnyx/voice")
async def telnyx_inbound_voice(
    CallSid: str = Form(default=""),
    CallControlId: str = Form(default=""),
    From: str = Form(default=""),
    To: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """
    Telnyx TeXML inbound webhook.
    """
    telnyx_id = CallSid or CallControlId or f"telnyx_{datetime.now(timezone.utc).timestamp()}"

    phone_rec = db.query(BusinessPhoneNumber).filter(
        BusinessPhoneNumber.phone_number == To,
        BusinessPhoneNumber.active == True,
    ).first()

    business = phone_rec.business if phone_rec else db.query(Business).first()
    if not business:
        texml = _generate_texml_response("This business is currently unavailable. Goodbye.", action_url="", is_final=True)
        return Response(content=texml, media_type="application/xml")

    call = db.query(Call).filter(Call.provider_call_id == telnyx_id).first()
    greeting = f"Hello, thank you for calling {business.name}. I am an AI voice receptionist. How may I help you today?"
    if not call:
        call = Call(
            business_id=business.id,
            provider_call_id=telnyx_id,
            caller_number=From,
            outcome="in_progress",
            transcript=[
                {
                    "role": "agent",
                    "content": greeting,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "telnyx_inbound",
                }
            ],
        )
        db.add(call)
        db.commit()

    gather_url = f"/api/telephony/telnyx/gather?call_sid={telnyx_id}"
    texml = _generate_texml_response(greeting, action_url=gather_url)
    return Response(content=texml, media_type="application/xml")


@router.post("/telnyx/gather")
async def telnyx_voice_gather(
    call_sid: str,
    SpeechResult: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """
    Telnyx TeXML speech result callback.
    """
    call = db.query(Call).filter(Call.provider_call_id == call_sid).first()
    if not call or call.outcome != "in_progress":
        texml = _generate_texml_response("Thank you for calling. Goodbye.", action_url="", is_final=True)
        return Response(content=texml, media_type="application/xml")

    user_text = SpeechResult.strip()
    if not user_text:
        gather_url = f"/api/telephony/telnyx/gather?call_sid={call_sid}"
        texml = _generate_texml_response("I could not hear what you said. Could you please repeat that?", action_url=gather_url)
        return Response(content=texml, media_type="application/xml")

    business = db.query(Business).filter(Business.id == call.business_id).first()
    business_name = business.name if business else "Our Business"
    tools = ReceptionistTools(db=db, business_id=call.business_id, call_id=call.id)
    agent = GeminiReceptionistAgent(business_name=business_name, tools=tools)

    history = list(call.transcript or [])
    try:
        turn_result = await run_in_threadpool(
            agent.process_turn,
            history=history,
            caller_message=user_text,
        )
    except Exception as exc:
        logger.error(f"[Telnyx Voice Gather Error] {exc}", exc_info=True)
        gather_url = f"/api/telephony/telnyx/gather?call_sid={call_sid}"
        fallback_msg = "I am having a brief moment processing that. Could you please repeat your question?"
        texml = _generate_texml_response(fallback_msg, action_url=gather_url)
        return Response(content=texml, media_type="application/xml")

    new_transcript = list(call.transcript or [])
    new_transcript.append({
        "role": "caller",
        "content": user_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "telnyx_speech",
    })
    new_transcript.append({
        "role": "agent",
        "content": turn_result.spoken_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_called": turn_result.tools_invoked,
    })
    call.transcript = new_transcript
    db.commit()

    is_farewell = any(w in user_text.lower() for w in ["bye", "goodbye", "that is all", "that's all", "hang up", "no thank you"])
    gather_url = f"/api/telephony/telnyx/gather?call_sid={call_sid}"
    texml = _generate_texml_response(turn_result.spoken_response, action_url=gather_url, is_final=is_farewell)
    return Response(content=texml, media_type="application/xml")


@router.post("/telnyx/status")
async def telnyx_call_status(
    CallSid: str = Form(default=""),
    CallControlId: str = Form(default=""),
    CallStatus: str = Form(default="completed"),
    db: Session = Depends(get_db),
):
    """
    Telnyx status callback when call terminates.
    """
    telnyx_id = CallSid or CallControlId
    call = db.query(Call).filter(Call.provider_call_id == telnyx_id).first()
    if call:
        call.outcome = CallStatus
        call.ended_at = datetime.now(timezone.utc)
        call.summary = f"Telnyx call completed with status '{CallStatus}'."
        db.commit()
    return {"status": "ok", "call_sid": telnyx_id}
