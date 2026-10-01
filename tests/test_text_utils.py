import pytest
from app.agent.text_utils import clean_reply_text, is_auto_reply


def test_clean_reply_text_strips_quotes():
    raw = (
        "I would prefer slot B please.\n"
        "> On Monday, Oct 5, Recruitment Team wrote:\n"
        "> Please pick a slot:\n"
        "> A) 10:00\n"
        "> B) 11:00\n"
    )
    cleaned = clean_reply_text(raw)
    assert "prefer slot B" in cleaned
    assert "On Monday" not in cleaned
    assert "Recruitment Team wrote" not in cleaned


def test_clean_reply_text_cuts_at_delimiter():
    raw = (
        "Slot C works best for me.\n"
        "-----Original Message-----\n"
        "From: recruiter@example.com\n"
        "Sent: Monday\n"
    )
    cleaned = clean_reply_text(raw)
    assert cleaned.strip() == "Slot C works best for me."


def test_clean_reply_text_cuts_at_on_wrote():
    raw = (
        "Let's do slot A.\n\n"
        "On Oct 5, 2026, at 10:00 AM, Recruitment Team <recruiter@example.com> wrote:\n"
        "Hi candidate..."
    )
    cleaned = clean_reply_text(raw)
    assert cleaned.strip() == "Let's do slot A."


def test_clean_reply_text_truncates_to_4000():
    raw = "A" * 5000
    cleaned = clean_reply_text(raw)
    assert len(cleaned) == 4000


def test_clean_reply_text_strips_control_chars():
    raw = "Slot A\x00\x07\x08 is good\nThank you\t!"
    cleaned = clean_reply_text(raw)
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "\x08" not in cleaned
    assert "Slot A is good\nThank you\t!" == cleaned


def test_is_auto_reply_headers():
    assert is_auto_reply("Re: Interview", {"Auto-Submitted": "auto-replied"}) is True
    assert is_auto_reply("Re: Interview", {"auto-submitted": "auto-generated"}) is True
    assert is_auto_reply("Re: Interview", {"Auto-Submitted": "no"}) is False
    assert is_auto_reply("Re: Interview", {"X-Autoreply": "yes"}) is True
    assert is_auto_reply("Re: Interview", {"Precedence": "bulk"}) is True
    assert is_auto_reply("Re: Interview", {"Precedence": "auto_reply"}) is True


def test_is_auto_reply_subjects():
    assert is_auto_reply("Automatic reply: Interview Invitation", {}) is True
    assert is_auto_reply("Out of office: Interview", None) is True
    assert is_auto_reply("Undeliverable: Interview", {}) is True
    assert is_auto_reply("Re: Interview Invitation", {}) is False
    assert is_auto_reply(None, None) is False
