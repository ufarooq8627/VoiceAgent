from pydantic import BaseModel, EmailStr


class CandidateCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    skills: list[str] | None = None
    experience_years: int | None = None
    current_company: str | None = None
    designation: str | None = None
    expected_salary: str | None = None
    resume_path: str | None = None
    timezone: str = "Asia/Kolkata"


class CandidateResponse(BaseModel):
    id: str
    job_id: str
    name: str
    email: str
    phone: str | None = None
    skills: list[str] | None = None
    experience_years: int | None = None
    current_company: str | None = None
    designation: str | None = None
    expected_salary: str | None = None
    resume_path: str | None = None
    source: str
    status: str
    timezone: str

    model_config = {"from_attributes": True}
