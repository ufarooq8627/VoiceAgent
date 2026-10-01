from pydantic import BaseModel


class JobCreate(BaseModel):
    title: str
    description: str


class JobUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None


class JobResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str

    model_config = {"from_attributes": True}
