from datetime import datetime, timezone
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from app.models.client_usage import ClientUsage

def get_current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")

def check_and_increment_usage(
    db: Session,
    business_id: str,
    period: Optional[str] = None,
    default_quota: int = 100
) -> Tuple[bool, str]:
    target_period = period or get_current_period()
    usage = db.query(ClientUsage).filter(
        ClientUsage.business_id == business_id,
        ClientUsage.billing_period == target_period
    ).first()

    if not usage:
        usage = ClientUsage(
            business_id=business_id,
            billing_period=target_period,
            calls_used=0,
            minutes_used=0,
            quota_limit=default_quota
        )
        db.add(usage)
        db.flush()

    if usage.calls_used >= usage.quota_limit:
        return False, f"Monthly call quota exceeded ({usage.calls_used}/{usage.quota_limit} calls used). Please upgrade subscription."

    usage.calls_used += 1
    db.commit()
    return True, "Usage incremented successfully"
