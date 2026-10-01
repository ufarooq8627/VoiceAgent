from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.schemas.candidate import CandidateCreate, CandidateResponse
from app.services.candidate_service import CandidateService

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
