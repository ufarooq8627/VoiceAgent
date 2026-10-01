from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import update

from app.models import Slot, Booking, Interviewer, Candidate
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
        mode: str = "virtual",
        location_or_link: str | None = None,
    ) -> list[Slot]:
        slots = []
        current = start_at_utc
        duration = timedelta(minutes=duration_minutes)

        while current + duration <= end_at_utc:
            slot = Slot(
                job_id=job_id,
                interviewer_id=interviewer_id,
                start_at_utc=current,
                end_at_utc=current + duration,
                mode=mode,
                location_or_link=location_or_link,
                status="open",
            )
            db.add(slot)
            slots.append(slot)
            current += duration

        db.commit()
        for s in slots:
            db.refresh(s)
        return slots

    @staticmethod
    def get_available(db: Session, job_id: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        slots = (
            db.query(Slot)
            .filter(
                Slot.job_id == job_id,
                Slot.status == "open",
                Slot.start_at_utc > now,
            )
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
        commit: bool = True,
        transition: bool = True,
    ) -> tuple[bool, Booking | str]:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            return False, "Candidate not found"

        if transition:
            allowed_statuses = {CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP}
            if actor == "recruiter":
                allowed_statuses.add(CandidateStatus.NEEDS_RECRUITER)

            if candidate.status not in allowed_statuses:
                return False, f"Candidate is in status {candidate.status}, cannot book"

        existing_booking = db.query(Booking).filter(
            Booking.candidate_id == candidate_id,
            Booking.status == "confirmed",
        ).first()
        if existing_booking:
            return False, "Candidate already has a confirmed booking"

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

        if transition:
            try:
                transition_candidate(
                    db,
                    candidate_id,
                    CandidateStatus.BOOKED,
                    actor=actor,
                    payload={"slot_id": slot_id},
                    commit=False,
                )
            except Exception as e:
                if commit:
                    db.rollback()
                return False, f"Failed state transition: {str(e)}"

        db.flush()
        if commit:
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
