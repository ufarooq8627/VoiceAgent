import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from datetime import datetime, timezone, timedelta
from app.database import Base, engine, SessionLocal
from app.models.receptionist import (
    Business, BusinessPhoneNumber, KnowledgeItem, LiveDataSource
)


def seed():
    print("Creating all tables in database...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    biz = db.query(Business).filter(Business.name == "Apex Dental & Wellness Clinic").first()
    if not biz:
        print("Seeding demo business...")
        biz = Business(
            name="Apex Dental & Wellness Clinic",
            timezone="America/New_York",
        )
        db.add(biz)
        db.commit()
        db.refresh(biz)

        phone = BusinessPhoneNumber(
            business_id=biz.id,
            phone_number="+15550001111",
            provider="mock",
            active=True,
        )
        db.add(phone)

        # Approved Static FAQs
        now = datetime.now(timezone.utc)
        faqs = [
            ("What are your opening hours?", "We are open Monday to Friday from 8:30 AM to 6:00 PM, and Saturdays from 9:00 AM to 2:00 PM.", "hours"),
            ("Where are you located?", "We are located at 450 Lexington Ave, Suite 1200, New York, NY.", "location"),
            ("Do you have parking?", "Free validated parking is available in the underground parking garage on level B2.", "parking"),
            ("What payment methods do you accept?", "We accept all major credit cards, debit cards, HSA/FSA cards, cash, and Apple Pay.", "billing"),
            ("What is your cancellation policy?", "Appointments can be rescheduled or cancelled with at least 24 hours notice without any penalty.", "policy"),
            ("What dental insurance do you accept?", "We participate in-network with Delta Dental, Cigna, MetLife, Aetna, and Guardian.", "insurance"),
        ]
        for q, a, cat in faqs:
            db.add(KnowledgeItem(
                business_id=biz.id,
                question=q,
                answer=a,
                category=cat,
                status="approved",
                valid_from=now - timedelta(days=30),
            ))

        # Live Data Source
        db.add(LiveDataSource(
            business_id=biz.id,
            source_type="appointment_slots",
            capabilities={"pricing": True, "availability": True},
            config_reference="default_dental_catalog",
            active=True,
            freshness_limit_seconds=300,
        ))

        db.commit()
        print(f"Demo business seeded successfully! ID: {biz.id}, Phone: +15550001111")
    else:
        print(f"Demo business already exists with ID: {biz.id}")

    db.close()


if __name__ == "__main__":
    seed()
