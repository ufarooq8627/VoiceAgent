"""
Idempotent migration for Phase 2 schema additions.
Adds:
- email_outbox.offered_slots (JSON)
- inbound_messages.attempts (INTEGER NOT NULL DEFAULT 0)
- inbound_messages.claimed_at (DATETIME)
- inbound_messages.last_error (VARCHAR(500))
- inbound_messages.message_id (VARCHAR(255) UNIQUE)
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import inspect, text
from app.database import engine, Base


def migrate():
    # Ensure tables exist first
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    with engine.begin() as conn:
        # 1. email_outbox columns
        email_cols = {c["name"] for c in inspector.get_columns("email_outbox")}
        if "offered_slots" not in email_cols:
            conn.execute(text("ALTER TABLE email_outbox ADD COLUMN offered_slots JSON"))
            print("Added column email_outbox.offered_slots")

        # 2. inbound_messages columns
        inbound_cols = {c["name"] for c in inspector.get_columns("inbound_messages")}
        if "attempts" not in inbound_cols:
            conn.execute(text("ALTER TABLE inbound_messages ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"))
            print("Added column inbound_messages.attempts")
        if "claimed_at" not in inbound_cols:
            conn.execute(text("ALTER TABLE inbound_messages ADD COLUMN claimed_at DATETIME"))
            print("Added column inbound_messages.claimed_at")
        if "last_error" not in inbound_cols:
            conn.execute(text("ALTER TABLE inbound_messages ADD COLUMN last_error VARCHAR(500)"))
            print("Added column inbound_messages.last_error")
        if "message_id" not in inbound_cols:
            conn.execute(text("ALTER TABLE inbound_messages ADD COLUMN message_id VARCHAR(255)"))
            print("Added column inbound_messages.message_id")

        # 3. Unique index on inbound_messages(message_id)
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_message_id ON inbound_messages(message_id)"))
        print("Ensured unique index ux_inbound_message_id on inbound_messages(message_id)")

    print("Phase 2 migration completed successfully.")


if __name__ == "__main__":
    migrate()
