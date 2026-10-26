import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import Business, Call, CallbackRequest, KnowledgeItem
from app.models.client_api_key import ClientApiKey, verify_client_secret
from app.services.widget_token_service import mint_widget_session_token, verify_widget_session_token

logger = logging.getLogger("app.portal_auth")
router = APIRouter(prefix="/portal", tags=["Client Self-Service Portal"])
templates = Jinja2Templates(directory="app/templates")

def get_current_tenant(request: Request, db: Session = Depends(get_db)) -> Business:
    token = request.cookies.get("portal_session")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = verify_widget_session_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    biz = db.query(Business).filter(Business.id == payload.get("business_id")).first()
    if not biz:
        raise HTTPException(status_code=401, detail="Tenant business not found")
    return biz

@router.get("/login", response_class=HTMLResponse)
def portal_login_page(request: Request):
    return templates.TemplateResponse(request=request, name="portal/login.html", context={"error": None})

@router.post("/login")
def portal_login(
    request: Request,
    response: Response,
    client_secret: str = Form(...),
    db: Session = Depends(get_db)
):
    keys = db.query(ClientApiKey).filter(ClientApiKey.is_active == True).all()
    matched_key = None
    for k in keys:
        if verify_client_secret(client_secret, k.secret_key_hash):
            matched_key = k
            break
            
    if not matched_key:
        return templates.TemplateResponse(
            request=request,
            name="portal/login.html",
            context={"error": "Invalid Secret API Key. Please verify and try again."},
            status_code=401
        )
    
    token = mint_widget_session_token(
        business_id=matched_key.business_id,
        origin="portal",
        client_ip=request.client.host if request.client else "unknown",
        ttl_seconds=86400  # 24 hours
    )
    redirect = RedirectResponse(url="/portal", status_code=303)
    redirect.set_cookie(key="portal_session", value=token, httponly=True, samesite="lax")
    return redirect

@router.get("/logout")
def portal_logout():
    redirect = RedirectResponse(url="/portal/login", status_code=303)
    redirect.delete_cookie("portal_session")
    return redirect

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def portal_home(
    request: Request,
    tenant: Business = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    key = db.query(ClientApiKey).filter(ClientApiKey.business_id == tenant.id, ClientApiKey.is_active == True).first()
    pub_key = key.public_key if key else "pk_live_none"
    allowed_origins = key.allowed_origins if key else []
    
    total_calls = db.query(Call).filter(Call.business_id == tenant.id).count()
    total_callbacks = db.query(CallbackRequest).filter(CallbackRequest.business_id == tenant.id).count()
    total_faqs = db.query(KnowledgeItem).filter(KnowledgeItem.business_id == tenant.id).count()

    return templates.TemplateResponse(
        request=request,
        name="portal/dashboard.html",
        context={
            "tenant": tenant,
            "public_key": pub_key,
            "allowed_origins": allowed_origins,
            "total_calls": total_calls,
            "total_callbacks": total_callbacks,
            "total_faqs": total_faqs
        }
    )
