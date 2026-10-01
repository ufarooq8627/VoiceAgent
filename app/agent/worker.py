import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal
from app.services.email_service import EmailService
from app.services.agent_service import AgentService
from app.providers.inbox_provider import get_inbox_provider
from app.models import InboundMessage

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def agent_tick():
    db = SessionLocal()
    try:
        # 1. Drain email outbox
        sent = EmailService.drain_outbox(db, batch_size=settings.outbox_batch_size)
        if sent > 0:
            logger.info(f"[agent_tick] Sent {sent} outbound emails")

        # 2. Poll inbox provider (mock returns [] in P1)
        inbox = get_inbox_provider()
        inbox.poll()

        # 3. Process unprocessed inbound replies
        unprocessed = (
            db.query(InboundMessage)
            .filter(InboundMessage.processed.is_(False))
            .all()
        )
        for msg in unprocessed:
            AgentService.process_reply(db, msg.id)

    except Exception as e:
        logger.error(f"[agent_tick] Error during agent tick: {e}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            agent_tick,
            trigger=IntervalTrigger(seconds=settings.agent_tick_interval_seconds),
            id="agent_tick_job",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[AgentWorker] Background scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[AgentWorker] Background scheduler stopped")
