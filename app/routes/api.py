import hmac
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.schemas.candidate import CandidateCreate, CandidateResponse
from app.schemas.inbound import IncomingEmail
from app.services.candidate_service import CandidateService
from app.services.inbound_service import InboundService
from app.config import settings
from app.limiter import limiter

router = APIRouter(prefix="/api", tags=["api"])


@router.post("/jobs/{id}/candidates", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def ingest_candidate(
    id: str,
    candidate_in: CandidateCreate,
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidate = CandidateService.create_from_api(db, job_id=id, data=candidate_in)
    return candidate


@router.post("/webhooks/incoming-email", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("60/minute")
def incoming_email(
    request: Request,
    payload: IncomingEmail,
    x_webhook_secret: str = Header(default=""),
    db: Session = Depends(get_db),
):
    expected = settings.webhook_secret
    if not expected or not hmac.compare_digest(x_webhook_secret.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")

    InboundService.ingest(
        db=db,
        from_address=payload.from_address,
        subject=payload.subject,
        body_text=payload.body_text,
        headers=payload.headers,
    )
    return {"status": "accepted"}
