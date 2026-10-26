import re

def format_speech_payload(text: str, max_chars: int = 250) -> str:
    """Cleans markdown characters and limits length for natural vocal response."""
    cleaned = re.sub(r"[*#_`~]", "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:!?") + "..."
