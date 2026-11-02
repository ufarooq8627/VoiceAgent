from fastapi.responses import RedirectResponse
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import Base, engine
from app.routes import auth, admin, public, api, receptionist_api, receptionist_admin, telephony_api, widget_api, client_api, portal_auth, portal_knowledge, portal_leads, outbound_admin, outbound_telephony
from app.agent.worker import start_scheduler, stop_scheduler
from app.limiter import limiter


import logging
logger = logging.getLogger("app.main")


def _require_current_schema():
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    script = ScriptDirectory.from_config(AlembicConfig(str(alembic_ini)))
    expected_heads = set(script.get_heads())
    with engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
    if current_heads != expected_heads:
        raise RuntimeError("Database migrations are missing or out of date; run 'alembic upgrade head' before starting the production app.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Production schema changes are applied before startup with Alembic.
    # Keep create_all for local development only; it does not migrate existing schemas.
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
    else:
        _require_current_schema()
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

allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(widget_api.router)
app.include_router(client_api.router)
app.include_router(portal_auth.router)
app.include_router(portal_knowledge.router)
app.include_router(portal_leads.router)
app.include_router(outbound_admin.router)
app.include_router(outbound_telephony.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/admin/mock-call", status_code=303)
