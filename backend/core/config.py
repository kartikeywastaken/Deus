"""Application configuration sourced from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TEXT_EMBEDDING_DIMENSION = 384
IMAGE_EMBEDDING_DIMENSION = 512


class Settings(BaseSettings):
    """Runtime settings with safe development defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://deus:pyarebache345%23%23@localhost:5433/deus"
    database_echo: bool = False

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    github_token: SecretStr | None = None
    ghunt_enabled: bool = False
    ghunt_auth_ready: bool = False
    ghunt_python: str = ""
    gitfive_enabled: bool = False
    gitfive_auth_ready: bool = False
    gitfive_binary: str = "gitfive"
    gitfive_python: str = ""
    hibp_enabled: bool = False
    hibp_api_key: SecretStr | None = None
    osintgram_enabled: bool = True
    osintgram_python: str = ""
    osintgram_source: str = ""
    osintgram_session_file: str = ""
    text_embeddings_enabled: bool = True
    ai_adviser_enabled: bool = False
    gemini_api_key: SecretStr | None = None
    ai_model: str = "gemini-2.5-flash"
    connector_concurrency: int = Field(default=4, ge=1, le=64)
    connector_timeout_seconds: float = Field(default=30.0, gt=0)
    discovery_timeout_seconds: float = Field(default=60.0, ge=55, le=120)

    max_pivot_depth: int = Field(default=3, ge=0)
    max_candidates: int = Field(default=100, ge=1)
    max_connector_runs: int = Field(default=30, ge=1)
    max_questions: int = Field(default=3, ge=0)
    max_search_duration_seconds: int = Field(default=600, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""

    return Settings()
