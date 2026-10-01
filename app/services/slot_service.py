from datetime import datetime, timedelta
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Slot, Booking, Interviewer
from app.services.state_machine import transition_candidate, CandidateStatus


class SlotService:
    @staticmethod
    def create_slots(
        db: Session,
        job_id: str,
        interviewer_id: str,
        start_at_utc: datetime,
        end_at_utc: datetime,
        duration_minutes: int = 30,
        mode: str = "video",
        location_or_link: str | None = None,
    ) -> list[Slot]:
        if end_at_utc <= start_at_utc:
            raise ValueError("end_at_utc must be greater than start_at_utc")

        step = timedelta(minutes=duration_minutes)
        current_start = start_at_utc
        slots = []

        while current_start + step <= end_at_utc:
            current_end = current_start + step

            # Overlap check for interviewer
            overlap = (
                db.query(Slot)
                .filter(
                    Slot.interviewer_id == interviewer_id,
                    Slot.status != "cancelled",
                    Slot.start_at_utc < current_end,
                    Slot.end_at_utc > current_start,
                )
                .first()
            )
            if overlap:
                raise ValueError(
                    f"Slot from {current_start} to {current_end} overlaps with an existing slot"
                )

            slot = Slot(
                job_id=job_id,
                interviewer_id=interviewer_id,
                start_at_utc=current_start,
                end_at_utc=current_end,
                mode=mode,
                location_or_link=location_or_link,
                status="open",
            )
            db.add(slot)
            slots.append(slot)
            current_start = current_end

        db.commit()
        for s in slots:
            db.refresh(s)
        return slots

    @staticmethod
    def get_available(db: Session, job_id: str) -> list[dict]:
        slots = (
            db.query(Slot)
            .filter(Slot.job_id == job_id, Slot.status == "open")
            .order_by(Slot.start_at_utc.asc())
            .all()
        )

        result = []
        for i, slot in enumerate(slots):
            label = chr(65 + i) if i < 26 else f"A{i}"
            interviewer_name = slot.interviewer.name if slot.interviewer else "Interviewer"
            result.append({
                "label": label,
                "id": slot.id,
                "slot": slot,
                "date": slot.start_at_utc.strftime("%Y-%m-%d"),
                "start_time": slot.start_at_utc.strftime("%H:%M UTC"),
                "end_time": slot.end_at_utc.strftime("%H:%M UTC"),
                "interviewer_name": interviewer_name,
                "mode": slot.mode,
                "location_or_link": slot.location_or_link,
            })
        return result

    @staticmethod
    def book(
        db: Session,
        slot_id: str,
        candidate_id: str,
        actor: str = "agent",
    ) -> tuple[bool, Booking | str]:
        # Atomic slot state update
        stmt = (
            update(Slot)
            .where(Slot.id == slot_id, Slot.status == "open")
            .values(status="booked")
        )
        res = db.execute(stmt)
        if res.rowcount == 0:
            return False, "Slot already booked or not available"

        booking = Booking(candidate_id=candidate_id, slot_id=slot_id, status="confirmed")
        db.add(booking)

        try:
            transition_candidate(
                db,
                candidate_id,
                CandidateStatus.BOOKED,
                actor=actor,
                payload={"slot_id": slot_id},
            )
        except Exception as e:
            db.rollback()
            return False, f"Failed state transition: {str(e)}"

        db.commit()
        db.refresh(booking)
        return True, booking

    @staticmethod
    def cancel(db: Session, slot_id: str) -> bool:
        slot = db.query(Slot).filter(Slot.id == slot_id).first()
        if not slot:
            return False
        slot.status = "cancelled"
        if slot.booking and slot.booking.status == "confirmed":
            slot.booking.status = "cancelled"
        db.commit()
        return True
