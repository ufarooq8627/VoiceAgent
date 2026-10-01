from sqlalchemy import update
from sqlalchemy.orm import Session
from app.models import Candidate, CandidateEvent


class CandidateStatus:
    NEW = "NEW"
    SHORTLISTED = "SHORTLISTED"
    INVITED = "INVITED"
    BOOKED = "BOOKED"
    INTERVIEWED = "INTERVIEWED"
    DECLINED = "DECLINED"
    NEEDS_RECRUITER = "NEEDS_RECRUITER"
    FOLLOW_UP = "FOLLOW_UP"
    NO_RESPONSE = "NO_RESPONSE"
    WAITLISTED = "WAITLISTED"


class IllegalTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Illegal transition: {from_status} -> {to_status}")


LEGAL_TRANSITIONS: dict[tuple[str, str], set[str]] = {
    (CandidateStatus.NEW, CandidateStatus.SHORTLISTED): {"recruiter"},
    (CandidateStatus.NEW, CandidateStatus.WAITLISTED): {"recruiter"},
    (CandidateStatus.SHORTLISTED, CandidateStatus.INVITED): {"system"},
    (CandidateStatus.INVITED, CandidateStatus.BOOKED): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.DECLINED): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.NEEDS_RECRUITER): {"agent", "candidate"},
    (CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP):
{"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.INVITED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.BOOKED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.DECLINED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.NEEDS_RECRUITER): {"agent"},
    (CandidateStatus.NEEDS_RECRUITER, CandidateStatus.INVITED): {"recruiter"},
    (CandidateStatus.NEEDS_RECRUITER, CandidateStatus.BOOKED): {"recruiter"},
    (CandidateStatus.BOOKED, CandidateStatus.INTERVIEWED): {"recruiter"},
}


def transition_candidate(
    db: Session,
    candidate_id: str,
    new_status: str,
    actor: str,
    payload: dict | None = None,
    commit: bool = True,
) -> Candidate:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")

    old_status = candidate.status
    key = (old_status, new_status)
    allowed_actors = LEGAL_TRANSITIONS.get(key)
    if allowed_actors is None or actor not in allowed_actors:
        raise IllegalTransition(old_status, new_status)

    stmt = (
        update(Candidate)
        .where(Candidate.id == candidate_id, Candidate.status == old_status)
        .values(status=new_status)
    )
    res = db.execute(stmt)
    if res.rowcount != 1:
        db.expire(candidate)
        db.refresh(candidate)
        raise IllegalTransition(candidate.status, new_status)

    candidate.status = new_status
    event = CandidateEvent(
        candidate_id=candidate_id,
        event_type=new_status.lower(),
        actor=actor,
        payload=payload,
    )
    db.add(event)
    db.flush()
    if commit:
        db.commit()
        db.refresh(candidate)
    return candidate
