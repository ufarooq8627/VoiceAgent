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
    (CandidateStatus.INVITED, CandidateStatus.FOLLOW_UP): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.INVITED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.BOOKED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.DECLINED): {"agent"},
    (CandidateStatus.FOLLOW_UP, CandidateStatus.NEEDS_RECRUITER): {"agent"},
    (CandidateStatus.BOOKED, CandidateStatus.INTERVIEWED): {"recruiter"},
}


def transition_candidate(db, candidate_id: str, new_status: str, actor: str, payload: dict | None = None) -> Candidate:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")

    key = (candidate.status, new_status)
    allowed_actors = LEGAL_TRANSITIONS.get(key)
    if allowed_actors is None or actor not in allowed_actors:
        raise IllegalTransition(candidate.status, new_status)

    candidate.status = new_status
    event = CandidateEvent(
        candidate_id=candidate_id,
        event_type=new_status.lower(),
        actor=actor,
        payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(candidate)
    return candidate
