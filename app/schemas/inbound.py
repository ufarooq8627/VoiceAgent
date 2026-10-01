from pydantic import BaseModel, Field


class IncomingEmail(BaseModel):
    from_address: str = Field(..., max_length=254)
    subject: str | None = Field(default=None, max_length=500)
    body_text: str = Field(..., max_length=20000)
    headers: dict[str, str] | None = None
