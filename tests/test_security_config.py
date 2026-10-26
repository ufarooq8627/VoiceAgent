import pytest
from pydantic import ValidationError
from app.config import Settings


def test_production_rejects_default_secret_key():
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            app_secret_key="change-me",
            admin_password="SuperSecretPassword123!",
            llm_provider="none",
            _env_file=None
        )
    assert "APP_SECRET_KEY must be set to a secure random value" in str(exc.value)


def test_production_rejects_empty_password_and_hash():
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="production",
            app_secret_key="a-very-long-and-secure-random-secret-key-for-prod",
            admin_password="",
            admin_password_hash="",
            llm_provider="none",
            _env_file=None
        )
    assert "ADMIN_PASSWORD_HASH or ADMIN_PASSWORD must be set in production" in str(exc.value)


def test_development_allows_defaults():
    s = Settings(
        environment="development",
        app_secret_key="change-me",
        llm_provider="none",
        _env_file=None
    )
    assert s.is_production is False
    assert s.app_secret_key == "change-me"


def test_env_example_has_no_hardcoded_bcrypt_hash():
    with open(".env.example", "r", encoding="utf-8") as f:
        content = f.read()

    # Must not ship a real bcrypt hash
    assert "$2b$12$" not in content
    assert "ADMIN_PASSWORD_HASH=" in content
