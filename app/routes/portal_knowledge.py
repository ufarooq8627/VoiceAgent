import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, KnowledgeItem
from app.routes.portal_auth import get_current_tenant

logger = logging.getLogger("app.portal_knowledge")
router = APIRouter(prefix="/portal/knowledge", tags=["Portal Knowledge Base"])
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def list_knowledge(
    request: Request,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    faqs = db.query(KnowledgeItem).filter(
        KnowledgeItem.business_id == tenant.id
    ).order_by(KnowledgeItem.updated_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="portal/knowledge.html",
        context={"tenant": tenant, "faqs": faqs}
    )

@router.post("/add")
def add_knowledge_item(
    request: Request,
    question: str = Form(...),
    answer: str = Form(...),
    category: str = Form("general"),
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    new_faq = KnowledgeItem(
        business_id=tenant.id,
        question=question.strip(),
        answer=answer.strip(),
        category=category.strip(),
        source="portal",
        status="approved"
    )
    db.add(new_faq)
    db.commit()
    return RedirectResponse(url="/portal/knowledge", status_code=303)

@router.post("/{faq_id}/edit")
def edit_knowledge_item(
    faq_id: str,
    question: str = Form(...),
    answer: str = Form(...),
    category: str = Form("general"),
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    faq = db.query(KnowledgeItem).filter(
        KnowledgeItem.id == faq_id,
        KnowledgeItem.business_id == tenant.id
    ).first()
    if not faq:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    faq.question = question.strip()
    faq.answer = answer.strip()
    faq.category = category.strip()
    faq.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url="/portal/knowledge", status_code=303)

@router.post("/{faq_id}/delete")
def delete_knowledge_item(
    faq_id: str,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    faq = db.query(KnowledgeItem).filter(
        KnowledgeItem.id == faq_id,
        KnowledgeItem.business_id == tenant.id
    ).first()
    if not faq:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    db.delete(faq)
    db.commit()
    return RedirectResponse(url="/portal/knowledge", status_code=303)
