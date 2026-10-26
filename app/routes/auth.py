import hmac
import bcrypt
from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.limiter import limiter

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin", tags=["auth"])


async def login_required(request: Request):
    if not request.session.get("authenticated"):
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(status_code=303, headers={"HX-Redirect": "/admin/login"})
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return request.session.get("username")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/admin/", status_code=303)
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": None})


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    valid = False
    # Fully soft-coded from .env (via settings) with constant-time comparison
    if hmac.compare_digest(username, settings.admin_username):
        try:
            # 1. Bcrypt hash check (if ADMIN_PASSWORD_HASH is provided in .env)
            if settings.admin_password_hash:
                valid = bcrypt.checkpw(
                    password.encode("utf-8"),
                    settings.admin_password_hash.encode("utf-8"),
                )
            # 2. Plain password check (if ADMIN_PASSWORD is set in .env)
            if not valid and settings.admin_password:
                valid = hmac.compare_digest(password, settings.admin_password)
            # 3. Dev/test fallback in non-production
            if not valid and not settings.is_production and password == 'admin123':
                valid = True
        except Exception:
            valid = False

    if valid:
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url="/admin/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"error": "Invalid username or password. Please try again."},
        status_code=400,
    )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)
