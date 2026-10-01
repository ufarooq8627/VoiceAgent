import re

CUTOFF_PATTERNS = [
    re.compile(r"^\s*-----Original Message-----", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*On\s+.+wrote:\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*_{32,}\s*$", re.MULTILINE),
]


def clean_reply_text(text: str) -> str:
    if not text:
        return ""

    # Cut off at quotation boundaries
    earliest_cutoff = len(text)
    for pattern in CUTOFF_PATTERNS:
        match = pattern.search(text)
        if match and match.start() < earliest_cutoff:
            earliest_cutoff = match.start()

    text = text[:earliest_cutoff]

    # Strip lines starting with '>'
    lines = []
    for line in text.splitlines():
        if line.strip().startswith(">"):
            continue
        lines.append(line)
    text = "\n".join(lines)

    # Strip control characters (except newline, tab, carriage return)
    cleaned_chars = [
        c for c in text
        if ord(c) >= 32 or c in ("\n", "\t", "\r")
    ]
    text = "".join(cleaned_chars)

    # Truncate to 4000 characters
    if len(text) > 4000:
        text = text[:4000]

    return text.strip()


def is_auto_reply(subject: str | None, headers: dict | None) -> bool:
    if headers:
        lower_headers = {str(k).lower(): str(v).lower() for k, v in headers.items()}

        # Auto-Submitted
        auto_sub = lower_headers.get("auto-submitted")
        if auto_sub and auto_sub != "no":
            return True

        # X-Autoreply
        if "x-autoreply" in lower_headers:
            return True

        # Precedence
        prec = lower_headers.get("precedence")
        if prec in ("bulk", "auto_reply", "junk"):
            return True

    if subject:
        sub = subject.strip().lower()
        if (
            sub.startswith("automatic reply:")
            or sub.startswith("out of office:")
            or sub.startswith("undeliverable:")
            or sub.startswith("auto-reply:")
        ):
            return True

    return False
