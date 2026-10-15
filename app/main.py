from fastapi.responses import RedirectResponse
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import Base, engine
from app.routes import auth, admin, public, api, receptionist_api, receptionist_admin, telephony_api
from app.agent.worker import start_scheduler, stop_scheduler
from app.limiter import limiter


import logging
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.is_production and settings.app_secret_key in ("change-me", "default", "secret", ""):
        logger.warning("[CRITICAL SECURITY WARNING] APP_SECRET_KEY is using a default insecure value! Set a random 32+ char key in .env.")
    if settings.is_production and not settings.admin_password_hash:
        logger.warning("[CRITICAL SECURITY WARNING] ADMIN_PASSWORD_HASH is empty in production mode! Admin dashboard login will be disabled until set.")
    
    if settings.enable_scheduler:
        start_scheduler()
    yield
    if settings.enable_scheduler:
        stop_scheduler()


app = FastAPI(title="Recruitment Agent", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    session_cookie="recruitment_admin_session",
    max_age=86400 * 7,
    same_site="lax",
    https_only=settings.is_production,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(public.router)
app.include_router(api.router)
app.include_router(receptionist_api.router)
app.include_router(receptionist_admin.router)
app.include_router(telephony_api.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/admin/mock-call", status_code=303)
