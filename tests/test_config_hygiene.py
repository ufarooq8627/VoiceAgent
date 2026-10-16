from pathlib import Path
from app.config import settings


def test_env_file_has_no_duplicate_keys():
    env_path = Path(".env")
    assert env_path.exists(), ".env file must exist"

    seen_keys = set()
    duplicates = []

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in seen_keys:
            duplicates.append(key)
        seen_keys.add(key)

    assert not duplicates, f"Duplicate keys found in .env: {duplicates}"


def test_settings_loaded_properly():
    assert settings.app_secret_key != "change-me"
    assert len(settings.app_secret_key) >= 32
    assert settings.telephony_webhook_token != ""
