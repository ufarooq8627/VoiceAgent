from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str = "change-me"
    admin_username: str = "admin"
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
    telephony_webhook_token: str = ""   # if set, require token in telephony webhooks
    environment: str = "development"     # development | production | test
    enable_scheduler: bool = True        # enable background candidate email tick

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @model_validator(mode="after")
    def validate_llm_config(self):
        if self.llm_provider == "gemini" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY must be set when LLM_PROVIDER is 'gemini'")
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
