from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = ""
    admin_password_hash: str = ""
    database_url: str = "sqlite:///./recruitment.db"
    email_provider: str = "mock"
    mock_inbox: bool = True
    agent_tick_interval_seconds: int = 30
    outbox_batch_size: int = 50
    llm_provider: str = "none"          # none | gemini
    llm_api_key: str = ""
    llm_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: int = 20
    agent_confidence_threshold: float = 0.7
    agent_max_clarifications: int = 2
    agent_max_llm_attempts: int = 3
    agent_claim_timeout_seconds: int = 300
    agent_context_messages: int = 10
    agent_max_outbound_per_day: int = 6
    webhook_secret: str = ""            # empty => webhook disabled
    telephony_webhook_token: str = ""   # inbound legacy token
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    environment: str = "development"     # development | production | test
    enable_scheduler: bool = True        # enable background candidate email tick

    # Outbound is fail-closed and runs only in a separate worker process.
    outbound_enabled: bool = False
    outbound_public_base_url: str = ""
    outbound_audio_dir: str = "storage/outbound_audio"
    outbound_audio_max_bytes: int = 20_000_000
    outbound_calls_per_second: float = 0.07
    outbound_max_concurrent_calls: int = 5
    outbound_poll_seconds: int = 3
    outbound_amd_timeout_seconds: int = 30
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @model_validator(mode="after")
    def validate_llm_config(self):
        if self.llm_provider == "gemini" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY must be set when LLM_PROVIDER is 'gemini'")
        return self

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.is_production:
            insecure_keys = ("change-me", "default", "secret", "", "change-me-to-a-secure-random-64-character-string")
            if self.app_secret_key in insecure_keys:
                raise ValueError("APP_SECRET_KEY must be set to a secure random value in production")
            if not self.admin_password_hash and not self.admin_password:
                raise ValueError("ADMIN_PASSWORD_HASH or ADMIN_PASSWORD must be set in production")
        return self

    @model_validator(mode="after")
    def validate_outbound_config(self):
        if self.outbound_enabled:
            if len(self.app_secret_key) < 32 or self.app_secret_key in ("change-me", "default", "secret"):
                raise ValueError("APP_SECRET_KEY must be a strong 32+ character value when outbound is enabled")
            if not self.twilio_account_sid or not self.twilio_auth_token:
                raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required when outbound is enabled")
            if not self.outbound_public_base_url.startswith("https://"):
                raise ValueError("OUTBOUND_PUBLIC_BASE_URL must be a public HTTPS URL when outbound is enabled")
            if self.outbound_calls_per_second <= 0 or self.outbound_max_concurrent_calls <= 0:
                raise ValueError("Outbound pacing and concurrency limits must be positive")
            if self.outbound_amd_timeout_seconds < 3 or self.outbound_amd_timeout_seconds > 59:
                raise ValueError("OUTBOUND_AMD_TIMEOUT_SECONDS must be between 3 and 59")
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
