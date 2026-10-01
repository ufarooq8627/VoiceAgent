import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal
from app.services.email_service import EmailService
from app.services.agent_service import AgentService
from app.agent.loop import process_candidate_messages
from app.providers.llm_provider import get_llm_provider
from app.providers.inbox_provider import get_inbox_provider
from app.models import InboundMessage

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def agent_tick(session_factory=SessionLocal, provider=None):
    provider = provider or get_llm_provider()
    with session_factory() as db:
        # 1. Poll inbox provider (mock returns [] in Phase 1/2)
        inbox = get_inbox_provider()
        if hasattr(inbox, "poll"):
            try:
                inbox.poll(db)
            except TypeError:
                inbox.poll()

        # 2. Get distinct candidates with unprocessed messages
        candidate_ids = [
            r[0]
            for r in (
                db.query(InboundMessage.candidate_id)
                .filter(
                    InboundMessage.processed.is_(False),
                    InboundMessage.candidate_id.isnot(None),
                )
                .distinct()
                .all()
            )
        ]

    for cid in candidate_ids:
        with session_factory() as db:
            try:
                process_candidate_messages(db, cid, provider)
            except Exception as exc:
                db.rollback()
                logger.error("agent tick failed candidate=%s err=%s", cid, type(exc).__name__)

    with session_factory() as db:
        EmailService.drain_outbox(db, settings.outbox_batch_size)


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            agent_tick,
            trigger=IntervalTrigger(seconds=settings.agent_tick_interval_seconds),
            id="agent_tick",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[AgentWorker] Background scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[AgentWorker] Background scheduler stopped")
