import bcrypt
from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

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
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    valid = False
    if username == settings.admin_username:
        try:
            if settings.admin_password_hash:
                valid = bcrypt.checkpw(
                    password.encode("utf-8"),
                    settings.admin_password_hash.encode("utf-8"),
                )
            elif not settings.is_production and password == "admin123":
                # Only allowed in non-production environments
                valid = True
        except Exception:
            # Fallback for local development if hash format had an issue
            if not settings.is_production and password == "admin123":
                valid = True

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
