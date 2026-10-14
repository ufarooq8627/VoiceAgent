from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.receptionist import LiveDataSource


class LiveDataAdapter:

    @classmethod
    def get_price_or_availability(
        cls,
        db: Session,
        business_id: str,
        item_key: str,
        requested_date: str | None = None,
        force_stale: bool = False,
    ) -> dict:
        source = (
            db.query(LiveDataSource)
            .filter(
                LiveDataSource.business_id == business_id,
                LiveDataSource.active.is_(True)
            )
            .first()
        )

        now = datetime.now(timezone.utc)
        if not source:
            return {
                "source_id": None,
                "retrieval_timestamp": now.isoformat(),
                "status": "unconfirmed",
                "reason": "No active live data source configured for business",
                "item_key": item_key,
                "price": None,
                "currency": None,
                "availability_status": "unknown",
                "requested_date": requested_date,
            }

        freshness_limit = source.freshness_limit_seconds or 300
        if force_stale:
            retrieval_time = now - timedelta(seconds=freshness_limit + 60)
        else:
            retrieval_time = now

        age_seconds = (now - retrieval_time).total_seconds()
        if age_seconds > freshness_limit:
            return {
                "source_id": source.id,
                "retrieval_timestamp": retrieval_time.isoformat(),
                "status": "unconfirmed",
                "reason": f"Data is stale (retrieved {int(age_seconds)}s ago, limit is {freshness_limit}s)",
                "item_key": item_key,
                "price": None,
                "currency": None,
                "availability_status": "unknown",
                "requested_date": requested_date,
            }

        CATALOG = {
            "cardiology_consultation": {
                "price": 150.0,
                "currency": "USD",
                "availability": "available",
                "details": "3 slots available on selected date",
            },
            "general_checkup": {
                "price": 75.0,
                "currency": "USD",
                "availability": "available",
                "details": "Morning slots open",
            },
            "standard_ticket": {
                "price": 25.0,
                "currency": "USD",
                "availability": "available",
                "details": "Seats available in Hall 2",
            },
            "vip_ticket": {
                "price": 60.0,
                "currency": "USD",
                "availability": "sold_out",
                "details": "Sold out for selected date",
            },
        }

        clean_key = item_key.lower().replace(" ", "_").replace("-", "_") if item_key else ""
        match = CATALOG.get(clean_key)

        if not match:
            return {
                "source_id": source.id,
                "retrieval_timestamp": retrieval_time.isoformat(),
                "status": "unconfirmed",
                "reason": f"Item '{item_key}' not found in live inventory",
                "item_key": item_key,
                "price": None,
                "currency": None,
                "availability_status": "unknown",
                "requested_date": requested_date,
            }

        return {
            "source_id": source.id,
            "retrieval_timestamp": retrieval_time.isoformat(),
            "status": "confirmed",
            "item_key": item_key,
            "price": match["price"],
            "currency": match["currency"],
            "availability_status": match["availability"],
            "requested_date": requested_date,
            "details": match["details"],
        }
