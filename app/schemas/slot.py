from datetime import datetime
from pydantic import BaseModel, Field


class SlotCreate(BaseModel):
    job_id: str
    interviewer_id: str
    start_at_utc: datetime
    end_at_utc: datetime
    mode: str = "video"
    location_or_link: str | None = None


class SlotWindowCreate(BaseModel):
    job_id: str
    interviewer_id: str
    start_at_utc: datetime
    end_at_utc: datetime
    duration_minutes: int = Field(default=30, ge=15, le=120)
    mode: str = "video"
    location_or_link: str | None = None


class SlotResponse(BaseModel):
    id: str
    job_id: str
    interviewer_id: str
    start_at_utc: datetime
    end_at_utc: datetime
    mode: str
    location_or_link: str | None = None
    status: str

    model_config = {"from_attributes": True}
