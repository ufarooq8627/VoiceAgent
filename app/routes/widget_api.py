import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.receptionist import Business
from app.models.client_api_key import ClientApiKey
from app.services.widget_token_service import mint_widget_session_token, verify_widget_session_token
from app.limiter import limiter

logger = logging.getLogger("app.widget_api")
router = APIRouter(prefix="/api/v1/widget", tags=["Web Voice Widget"])

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
