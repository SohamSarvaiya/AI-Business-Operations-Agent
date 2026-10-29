from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/business_ops"

    # LLM providers: mock | openai | anthropic | gemini
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    gemini_api_key: str = Field("", validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key"))
    gemini_model: str = "gemini-2.5-flash"

    # Agent behaviour
    max_iterations: int = 12
    max_nudges: int = 2
    llm_max_retries: int = 3
    llm_retry_backoff_seconds: float = 1.0
    tool_result_max_chars: int = 12000
    enable_write_tools: bool = False
    currency: str = "INR"
    today_override: str = ""  # YYYY-MM-DD, for demos/tests


@lru_cache
def get_settings() -> Settings:
    return Settings()
