from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import EmailOutbox, Candidate, Job, ConversationMessage
from app.services.state_machine import transition_candidate, CandidateStatus
from app.services.slot_service import SlotService
from app.services.invitation_service import InvitationService
from app.providers.email_provider import get_email_provider, BaseEmailProvider


class EmailService:
    @staticmethod
    def enqueue(
        db: Session,
        candidate_id: str | None,
        kind: str,
        to_address: str,
        subject: str,
        body_html: str,
        body_text: str,
        send_after: datetime | None = None,
    ) -> EmailOutbox:
        outbox = EmailOutbox(
            candidate_id=candidate_id,
            kind=kind,
            to_address=to_address,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            status="queued",
            send_after=send_after,
        )
        db.add(outbox)
        db.commit()
        db.refresh(outbox)
        return outbox

    @classmethod
    def enqueue_invitation_batch(
        cls,
        db: Session,
        job_id: str,
        candidate_ids: list[str],
        base_url: str = "",
    ) -> list[EmailOutbox]:
        job = db.query(Job).filter(Job.id == job_id).first()
        job_title = job.title if job else "the position"
        available_slots = SlotService.get_available(db, job_id)

        slots_text = "\n".join(
            f"{s['label']}: {s['date']} {s['start_time']} - {s['end_time']} (Interviewer: {s['interviewer_name']}, Mode: {s['mode']})"
            for s in available_slots
        )
        slots_html = "<ul>" + "".join(
            f"<li><strong>Slot {s['label']}</strong>: {s['date']} from {s['start_time']} to {s['end_time']} with {s['interviewer_name']} ({s['mode']})</li>"
            for s in available_slots
        ) + "</ul>"

        outbox_items = []
        for cid in candidate_ids:
            candidate = db.query(Candidate).filter(Candidate.id == cid).first()
            if not candidate:
                continue

            # State transition to INVITED
            transition_candidate(db, candidate.id, CandidateStatus.INVITED, actor="system")

            # Create invitation token
            invitation, raw_token = InvitationService.create_invitation(db, candidate.id)

            fallback_link = f"{base_url.rstrip('/')}/i/{raw_token}" if base_url else f"/i/{raw_token}"

            subject = f"Interview Invitation: {job_title}"
            body_text = (
                f"Hi {candidate.name},\n\n"
                f"You have been shortlisted for the role of {job_title}!\n\n"
                f"Please reply directly to this email with the letter of your preferred time slot:\n\n"
                f"{slots_text}\n\n"
                f"If none of these times work, reply to let us know.\n"
                f"Alternatively, you may book via your personal link: {fallback_link}\n\n"
                f"Best regards,\nRecruitment Team"
            )
            body_html = (
                f"<p>Hi {candidate.name},</p>"
                f"<p>You have been shortlisted for the role of <strong>{job_title}</strong>!</p>"
                f"<p>Please reply directly to this email with the letter of your preferred time slot:</p>"
                f"{slots_html}"
                f"<p>If none of these times work, please reply to let us know.</p>"
                f"<p style='color: #666; font-size: 13px;'>Fallback booking link: <a href='{fallback_link}'>{fallback_link}</a></p>"
                f"<p>Best regards,<br>Recruitment Team</p>"
            )

            outbox = cls.enqueue(
                db=db,
                candidate_id=candidate.id,
                kind="invitation",
                to_address=candidate.email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )

            # Record in conversation messages
            conv = ConversationMessage(
                candidate_id=candidate.id,
                direction="outbound",
                outbox_id=outbox.id,
                summary=f"Sent interview invitation with {len(available_slots)} available slots",
            )
            db.add(conv)
            outbox_items.append(outbox)

        db.commit()
        return outbox_items

    @staticmethod
    def drain_outbox(
        db: Session,
        batch_size: int = 50,
        provider: BaseEmailProvider | None = None,
    ) -> int:
        if provider is None:
            provider = get_email_provider()

        now = datetime.now(timezone.utc)
        items = (
            db.query(EmailOutbox)
            .filter(
                EmailOutbox.status == "queued",
                (EmailOutbox.send_after.is_(None)) | (EmailOutbox.send_after <= now),
            )
            .order_by(EmailOutbox.created_at.asc())
            .limit(batch_size)
            .all()
        )

        sent_count = 0
        for item in items:
            try:
                ok = provider.send(
                    to_address=item.to_address,
                    subject=item.subject,
                    body_html=item.body_html,
                    body_text=item.body_text,
                )
                if ok:
                    item.status = "sent"
                    item.sent_at = datetime.now(timezone.utc)
                    item.attempts += 1
                    sent_count += 1
                else:
                    item.status = "failed"
                    item.last_error = "Provider failed to send"
                    item.attempts += 1
            except Exception as e:
                item.status = "failed"
                item.last_error = str(e)
                item.attempts += 1

        db.commit()
        return sent_count
