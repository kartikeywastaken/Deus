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

    database_url: str = "postgresql+asyncpg://osint:osint-dev@localhost:5432/osint"
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

    # ── Face matching ──────────────────────────────────────────────────────
    face_matching_enabled: bool = True
    # InsightFace model pack — buffalo_sc (compact ArcFace, 512-D, research only)
    face_model_name: str = "buffalo_sc"
    # Max simultaneous face inference threads (CPU-bound, keep conservative)
    face_inference_concurrency: int = Field(default=2, ge=1, le=8)
    # Reference image upload limits
    max_face_upload_bytes: int = Field(default=8_000_000, ge=1)
    # Retention: raw reference image bytes are deleted after this many hours.
    # Embeddings and evidence are kept with the investigation.
    reference_image_retention_hours: int = Field(default=72, ge=1)
    face_embedding_retention_days: int = Field(default=30, ge=1)
    # Similarity thresholds (UNCALIBRATED — see backend/faces/similarity.py)
    # These have NOT been evaluated against a labelled ground-truth dataset.
    face_review_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    face_support_threshold: float = Field(default=0.68, ge=0.0, le=1.0)
    face_strong_support_threshold: float = Field(default=0.82, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""

    return Settings()
