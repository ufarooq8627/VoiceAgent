from datetime import datetime, timezone, timedelta
from sqlalchemy import update, or_
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.models import Candidate, InboundMessage, CandidateEvent
from app.services.state_machine import CandidateStatus, transition_candidate
from app.schemas.agent import AgentDecision
from app.agent.tools import AgentTools
from app.agent.text_utils import clean_reply_text, is_auto_reply
from app.agent import messages
from app.config import settings
from app.providers.llm_provider import (
    BaseLLMProvider,
    LLMTransientError,
    LLMPermanentError,
)

ACTIVE = {CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP}


def process_candidate_messages(db: Session, candidate_id: str, provider: BaseLLMProvider) -> None:
    msgs = (
        db.query(InboundMessage)
        .filter(InboundMessage.candidate_id == candidate_id, InboundMessage.processed.is_(False))
        .order_by(InboundMessage.received_at.asc())
        .all()
    )
    for msg in msgs:
        if not _claim(db, msg.id):
            break  # someone else owns it or fresh claim; preserve ordering
        if _process_one(db, msg, provider):  # True => stop (transient failure)
            break


def _claim(db: Session, msg_id: str) -> bool:
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=settings.agent_claim_timeout_seconds)
    # Support both SQLite naive comparison and Postgres aware comparison
    stale_naive = stale.replace(tzinfo=None)
    res = db.execute(
        update(InboundMessage)
        .where(
            InboundMessage.id == msg_id,
            InboundMessage.processed.is_(False),
            or_(
                InboundMessage.claimed_at.is_(None),
                InboundMessage.claimed_at < stale,
                InboundMessage.claimed_at < stale_naive,
            ),
        )
        .values(claimed_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount == 1


def _process_one(db: Session, msg: InboundMessage, provider: BaseLLMProvider) -> bool:
    tools = None
    try:
        cand = db.query(Candidate).filter(Candidate.id == msg.candidate_id).first()
        tools = AgentTools(db, msg.candidate_id)

        if cand is None or is_auto_reply(msg.subject, msg.raw_headers):
            return _finish(db, msg, "ignored_auto_reply")

        if cand.status not in ACTIVE:
            db.add(
                CandidateEvent(
                    candidate_id=cand.id,
                    event_type="inbound_after_close",
                    actor="agent",
                    payload={"inbound_id": msg.id, "status": cand.status},
                )
            )
            return _finish(db, msg, "ignored_status")

        text = clean_reply_text(msg.body_text)
        if not text:
            return _finish(db, msg, "ignored_empty")

        if tools.outbound_count_last_day() >= settings.agent_max_outbound_per_day:
            return _escalate(db, tools, msg, "Outbound email cap reached")



        try:
            decision = provider.classify(text, tools.get_candidate_context())
        except LLMTransientError as exc:
            return _fail(db, tools, msg, exc, transient=True)
        except (LLMPermanentError, ValidationError) as exc:
            return _fail(db, tools, msg, exc, transient=False)

        audit = decision.model_dump()
        if decision.confidence < settings.agent_confidence_threshold:
            return _escalate(db, tools, msg, "Low confidence", audit)

        return _dispatch(db, tools, cand, msg, decision, audit)
    except Exception as exc:
        db.rollback()
        return _fail(db, tools, msg, exc, transient=True)


def _dispatch(
    db: Session,
    tools: AgentTools,
    cand: Candidate,
    msg: InboundMessage,
    decision: AgentDecision,
    audit: dict,
) -> bool:
    intent = decision.intent

    if intent == "choose":
        res = tools.book_slot(decision.slot_label or "")
        if res.get("success"):
            return _finish(db, msg, "booked", audit)

        reason = res.get("reason")
        if reason == "slot_taken":
            slots = tools.current_slots()
            if not slots:
                return _escalate(db, tools, msg, "No slots remaining", audit)
            offered_dict = {s["label"]: s["id"] for s in slots}
            tools.send("slot_taken", messages.slot_taken(cand, slots), offered_slots=offered_dict)
            if cand.status == CandidateStatus.INVITED:
                transition_candidate(db, cand.id, CandidateStatus.FOLLOW_UP, "agent", commit=False)
            return _finish(db, msg, "slot_taken_reoffered", audit)

        elif reason in ("unknown_label", "invalid_label"):
            return _handle_unclear(db, tools, cand, msg, audit)

        elif reason == "illegal_state":
            return _finish(db, msg, "ignored_status", audit)

        else:
            return _escalate(db, tools, msg, f"Booking failure: {reason}", audit)

    elif intent == "unclear":
        return _handle_unclear(db, tools, cand, msg, audit)

    elif intent == "decline":
        tools.mark_declined(decision.reason or "Candidate declined")
        return _finish(db, msg, "declined", audit)

    elif intent in ("none_fit", "question"):
        escalation_reason = "None of the slots fit" if intent == "none_fit" else "Candidate asked a question"
        return _escalate(db, tools, msg, escalation_reason, audit)

    else:
        return _escalate(db, tools, msg, f"Unhandled intent {intent}", audit)


def _handle_unclear(
    db: Session,
    tools: AgentTools,
    cand: Candidate,
    msg: InboundMessage,
    audit: dict,
) -> bool:
    if tools.clarification_count() >= settings.agent_max_clarifications:
        return _escalate(db, tools, msg, "Too many clarification rounds", audit)

    slots = tools.current_slots()
    if not slots:
        return _escalate(db, tools, msg, "No slots remaining", audit)

    offered_dict = {s["label"]: s["id"] for s in slots}
    tools.send("clarification", messages.clarification(cand, slots), offered_slots=offered_dict)
    if cand.status == CandidateStatus.INVITED:
        transition_candidate(db, cand.id, CandidateStatus.FOLLOW_UP, "agent", commit=False)
    return _finish(db, msg, "clarification_sent", audit)


def _finish(
    db: Session,
    msg: InboundMessage,
    action: str,
    audit: dict | None = None,
) -> bool:
    msg.processed = True
    msg.claimed_at = None
    res = {**(audit or {}), "action": action}
    msg.agent_result = res
    if msg.candidate_id and action not in ("ignored_auto_reply", "ignored_empty", "ignored_status"):
        db.add(
            CandidateEvent(
                candidate_id=msg.candidate_id,
                event_type="reply_received",
                actor="candidate",
                payload={"inbound_id": msg.id, "action": action},
            )
        )
    db.commit()
    return False


def _escalate(
    db: Session,
    tools: AgentTools,
    msg: InboundMessage,
    reason: str,
    audit: dict | None = None,
) -> bool:
    tools.escalate_to_recruiter(reason)
    return _finish(db, msg, "escalated", audit)


def _fail(
    db: Session,
    tools: AgentTools | None,
    msg: InboundMessage,
    exc: Exception,
    transient: bool,
) -> bool:
    db.rollback()
    msg.attempts += 1
    msg.last_error = f"{type(exc).__name__}"[:500]
    msg.claimed_at = None

    if not transient or msg.attempts >= settings.agent_max_llm_attempts:
        escalate_reason = "LLM unavailable" if transient else "LLM output invalid"
        if tools:
            try:
                tools.escalate_to_recruiter(escalate_reason)
            except Exception:
                pass
        msg.processed = True
        msg.agent_result = {"action": "escalated", "error": msg.last_error}
        if msg.candidate_id:
            db.add(
                CandidateEvent(
                    candidate_id=msg.candidate_id,
                    event_type="reply_received",
                    actor="candidate",
                    payload={"inbound_id": msg.id, "action": "escalated"},
                )
            )
        db.commit()
        return False
    else:
        db.commit()
        return True
