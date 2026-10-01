from typing import Literal
from pydantic import BaseModel, Field, model_validator


class AgentDecision(BaseModel):
    intent: Literal["choose", "decline", "none_fit", "unclear", "question"]
    slot_label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)   # short audit note, never shown to candidate
    decline_reason: str | None = None                 # backwards compatibility
    follow_up_message: str | None = None              # backwards compatibility

    @model_validator(mode="after")
    def _check(self):
        if self.intent == "choose":
            if not self.slot_label or not self.slot_label.strip():
                raise ValueError("slot_label required for choose")
            self.slot_label = self.slot_label.strip().upper()[:2]
        else:
            self.slot_label = None
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
