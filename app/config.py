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
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    agent_confidence_threshold: float = 0.5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
