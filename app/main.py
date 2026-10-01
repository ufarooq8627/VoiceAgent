from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.routes import auth, admin, public, api
from app.agent.worker import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables created and start background agent worker
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(title="Recruitment Agent", version="0.1.0", lifespan=lifespan)

# Session middleware for cookie-based admin auth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    session_cookie="recruitment_admin_session",
    max_age=86400 * 7,  # 7 days
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(public.router)
app.include_router(api.router)


@app.get("/health")
def health():
    return {"status": "ok"}
