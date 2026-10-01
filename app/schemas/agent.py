from typing import Literal
from pydantic import BaseModel, model_validator


class AgentDecision(BaseModel):
    intent: Literal["choose", "decline", "none_fit", "unclear"]
    slot_label: str | None = None
    decline_reason: str | None = None
    follow_up_message: str | None = None
    confidence: float

    @model_validator(mode="after")
    def validate_slot_required(self):
        if self.intent == "choose" and not self.slot_label:
            raise ValueError("slot_label required when intent is 'choose'")
        return self


class SlotInfo(BaseModel):
    label: str
    date: str
    start_time: str
    end_time: str
    interviewer_name: str
    mode: str


class CandidateContext(BaseModel):
    candidate_id: str
    name: str
    email: str
    job_id: str
    job_title: str
    status: str
    conversation_history: list[dict]
