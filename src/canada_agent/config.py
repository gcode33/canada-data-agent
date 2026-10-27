"""Settings from the environment or a gitignored `.env`. Keys are SecretStr, so they never print."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://canada:canada@localhost:5432/canada"
    anthropic_api_key: SecretStr = SecretStr("")
    voyage_api_key: SecretStr = SecretStr("")

    agent_model: str = "claude-sonnet-5-5"
    ci_model: str = "claude-haiku-5-5"

    max_tool_calls: int = 8
    question_timeout_s: float = 60.0
    statcan_max_rps: float = 10.0
