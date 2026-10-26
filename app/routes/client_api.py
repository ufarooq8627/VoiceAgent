import logging
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.client_api_key import ClientApiKey, verify_client_secret
from app.models.receptionist import Business, KnowledgeItem, CallbackRequest, UnansweredEnquiry

logger = logging.getLogger("app.client_api")
router = APIRouter(prefix="/api/v1/client", tags=["Client B2B Management"])

def authenticate_client_secret(
    x_client_secret: Optional[str] = Header(None, alias="X-Client-Secret"),
    db: Session = Depends(get_db)
) -> ClientApiKey:
    if not x_client_secret:
        raise HTTPException(status_code=401, detail="Missing X-Client-Secret header")
    
    keys = db.query(ClientApiKey).filter(ClientApiKey.is_active == True).all()
    matched_key = None
    for k in keys:
        if verify_client_secret(x_client_secret, k.secret_key_hash):
            matched_key = k
            break
            
    if not matched_key:
        raise HTTPException(status_code=401, detail="Invalid client secret key")
    return matched_key

class FAQItemSync(BaseModel):
    question: str
    answer: str
    category: str = "general"

class KnowledgeSyncRequest(BaseModel):
    items: List[FAQItemSync]

@router.post("/knowledge/sync")
def sync_knowledge(
    payload: KnowledgeSyncRequest,
    client_key: ClientApiKey = Depends(authenticate_client_secret),
    db: Session = Depends(get_db)
):
    biz_id = client_key.business_id
    count = 0
    now = datetime.now(timezone.utc)
    for item in payload.items:
        existing = db.query(KnowledgeItem).filter(
            KnowledgeItem.business_id == biz_id,
            KnowledgeItem.question == item.question
        ).first()
        if existing:
            existing.answer = item.answer
            existing.category = item.category
            existing.updated_at = now
        else:
            new_item = KnowledgeItem(
                business_id=biz_id,
                question=item.question,
                answer=item.answer,
                category=item.category,
                source="client_api",
                status="approved"
            )
            db.add(new_item)
        count += 1
    db.commit()
    return {"status": "success", "synced_count": count}

@router.get("/leads")
def get_client_leads(
    client_key: ClientApiKey = Depends(authenticate_client_secret),
    db: Session = Depends(get_db)
):
    biz_id = client_key.business_id
    callbacks = db.query(CallbackRequest).filter(
        CallbackRequest.business_id == biz_id
    ).order_by(CallbackRequest.created_at.desc()).all()
    
    unanswered = db.query(UnansweredEnquiry).filter(
        UnansweredEnquiry.business_id == biz_id
    ).order_by(UnansweredEnquiry.created_at.desc()).all()

    return {
        "callbacks": [
            {
                "id": c.id,
                "customer_name": c.customer_name,
                "callback_number": c.callback_number,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in callbacks
        ],
        "unanswered": [
            {
                "id": u.id,
                "question": u.question,
                "failure_reason": u.failure_reason,
                "status": u.status,
                "created_at": u.created_at.isoformat() if u.created_at else None
            }
            for u in unanswered
        ]
    }
