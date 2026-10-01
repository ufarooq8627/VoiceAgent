import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def format_slot_time(dt: datetime, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        dt = dt.astimezone(tz)

    return dt.strftime("%a %d %b, %I:%M %p %Z")


def _format_slot_line(s: dict) -> str:
    when = s.get("when")
    if not when:
        when = f"{s.get('date', '')} {s.get('start_time', '')}".strip()
    mode = s.get("mode", "virtual")
    return f"{s['label']}: {when} ({mode})"


def _format_slot_html(s: dict) -> str:
    when = s.get("when")
    if not when:
        when = f"{s.get('date', '')} {s.get('start_time', '')}".strip()
    mode = s.get("mode", "virtual")
    return f"<li><strong>Slot {html.escape(str(s['label']))}</strong>: {html.escape(str(when))} ({html.escape(str(mode))})</li>"


def confirmation(candidate, slot) -> dict:
    job_title = candidate.job.title if candidate.job else "Position"
    tz = getattr(candidate, "timezone", "UTC") or "UTC"
    when = format_slot_time(slot.start_at_utc, tz)
    interviewer_name = slot.interviewer.name if slot.interviewer else "the interviewer"
    mode = slot.mode
    location = slot.location_or_link or "Virtual meeting link will be shared shortly"

    subject = f"Re: Interview invitation – {job_title}"
    body_text = (
        f"Hi {candidate.name},\n\n"
        f"Your interview for the {job_title} role has been confirmed!\n\n"
        f"Date & Time: {when}\n"
        f"Interviewer: {interviewer_name}\n"
        f"Mode: {mode}\n"
        f"Location / Link: {location}\n\n"
        f"Best regards,\nRecruitment Team"
    )
    body_html = (
        f"<p>Hi {html.escape(candidate.name)},</p>"
        f"<p>Your interview for the <strong>{html.escape(job_title)}</strong> role has been confirmed!</p>"
        f"<ul>"
        f"<li><strong>Date & Time:</strong> {html.escape(when)}</li>"
        f"<li><strong>Interviewer:</strong> {html.escape(interviewer_name)}</li>"
        f"<li><strong>Mode:</strong> {html.escape(mode)}</li>"
        f"<li><strong>Location / Link:</strong> {html.escape(location)}</li>"
        f"</ul>"
        f"<p>Best regards,<br>Recruitment Team</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}


def clarification(candidate, open_slots: list[dict]) -> dict:
    job_title = candidate.job.title if candidate.job else "Position"
    slots_text = "\n".join(_format_slot_line(s) for s in open_slots)
    slots_html = "<ul>" + "".join(_format_slot_html(s) for s in open_slots) + "</ul>"

    subject = f"Re: Interview invitation – {job_title}"
    body_text = (
        f"Hi {candidate.name},\n\n"
        f"We received your message regarding the interview for {job_title}.\n"
        f"Could you please clarify which time slot works best for you?\n\n"
        f"{slots_text}\n\n"
        f"Reply with the letter of the slot you'd like, or use the booking link in our first email.\n\n"
        f"Best regards,\nRecruitment Team"
    )
    body_html = (
        f"<p>Hi {html.escape(candidate.name)},</p>"
        f"<p>We received your message regarding the interview for <strong>{html.escape(job_title)}</strong>.</p>"
        f"<p>Could you please clarify which time slot works best for you?</p>"
        f"{slots_html}"
        f"<p>Reply with the letter of the slot you'd like, or use the booking link in our first email.</p>"
        f"<p>Best regards,<br>Recruitment Team</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}


def slot_taken(candidate, open_slots: list[dict]) -> dict:
    job_title = candidate.job.title if candidate.job else "Position"
    slots_text = "\n".join(_format_slot_line(s) for s in open_slots)
    slots_html = "<ul>" + "".join(_format_slot_html(s) for s in open_slots) + "</ul>"

    subject = f"Re: Interview invitation – {job_title}"
    body_text = (
        f"Hi {candidate.name},\n\n"
        f"The slot you selected was just booked by another candidate.\n"
        f"Here are the remaining available time slots:\n\n"
        f"{slots_text}\n\n"
        f"Reply with the letter of the slot you'd like, or use the booking link in our first email.\n\n"
        f"Best regards,\nRecruitment Team"
    )
    body_html = (
        f"<p>Hi {html.escape(candidate.name)},</p>"
        f"<p>The slot you selected was just booked by another candidate.</p>"
        f"<p>Here are the remaining available time slots:</p>"
        f"{slots_html}"
        f"<p>Reply with the letter of the slot you'd like, or use the booking link in our first email.</p>"
        f"<p>Best regards,<br>Recruitment Team</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}


def declined_ack(candidate) -> dict:
    job_title = candidate.job.title if candidate.job else "Position"
    subject = f"Re: Interview invitation – {job_title}"
    body_text = (
        f"Hi {candidate.name},\n\n"
        f"Thank you for letting us know. We have updated our records that you do not wish to proceed with the {job_title} application at this time.\n\n"
        f"We wish you all the best in your career pursuits!\n\n"
        f"Best regards,\nRecruitment Team"
    )
    body_html = (
        f"<p>Hi {html.escape(candidate.name)},</p>"
        f"<p>Thank you for letting us know. We have updated our records that you do not wish to proceed with the <strong>{html.escape(job_title)}</strong> application at this time.</p>"
        f"<p>We wish you all the best in your career pursuits!</p>"
        f"<p>Best regards,<br>Recruitment Team</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}


def escalation_ack(candidate) -> dict:
    job_title = candidate.job.title if candidate.job else "Position"
    subject = f"Re: Interview invitation – {job_title}"
    body_text = (
        f"Hi {candidate.name},\n\n"
        f"Thank you for your response regarding the {job_title} position.\n\n"
        f"We have forwarded your note to our recruiting team. A recruiter will review your message and follow up with you directly.\n\n"
        f"Best regards,\nRecruitment Team"
    )
    body_html = (
        f"<p>Hi {html.escape(candidate.name)},</p>"
        f"<p>Thank you for your response regarding the <strong>{html.escape(job_title)}</strong> position.</p>"
        f"<p>We have forwarded your note to our recruiting team. A recruiter will review your message and follow up with you directly.</p>"
        f"<p>Best regards,<br>Recruitment Team</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}
