"""Typed values exchanged between OSINT connectors and the orchestrator.

The connector boundary intentionally uses a small, stable schema.  Third-party
tool output belongs in ``raw_records``; the rest of the application should only
consume the normalized fields defined here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectorInputType(StrEnum):
    """Inputs that may make a connector eligible for execution."""

    USERNAME = "USERNAME"
    NAME = "NAME"
    PROFILE_URL = "PROFILE_URL"
    IMAGE = "IMAGE"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PROFILE = "PROFILE"
    GITHUB_PROFILE = "GITHUB_PROFILE"
    INSTAGRAM_PROFILE = "INSTAGRAM_PROFILE"
    GOOGLE_IDENTIFIER = "GOOGLE_IDENTIFIER"


class ProducedArtifactType(StrEnum):
    """Normalized artifacts a connector can emit."""

    PROFILE = "PROFILE"
    PROFILE_OBSERVATION = "PROFILE_OBSERVATION"
    USERNAME = "USERNAME"
    USERNAME_HISTORY = "USERNAME_HISTORY"
    URL = "URL"
    IDENTIFIER = "IDENTIFIER"
    EMAIL_IDENTIFIER = "EMAIL_IDENTIFIER"
    RELATIONSHIP = "RELATIONSHIP"
    OBSERVATION = "OBSERVATION"
    REPOSITORY = "REPOSITORY"


class ConnectorRunStatus(StrEnum):
    """Terminal statuses for a single connector invocation."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NO_RESULTS = "NO_RESULTS"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    FAILED = "FAILED"
    MANUAL = "MANUAL"


class ConnectorMode(StrEnum):
    """Only live execution exists."""

    LIVE = "LIVE"


class ConnectorAvailability(StrEnum):
    """The availability of a connector in its current runtime mode."""

    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    MANUAL = "MANUAL"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class IdentifierType(StrEnum):
    USERNAME = "USERNAME"
    DISPLAY_NAME = "DISPLAY_NAME"
    URL = "URL"
    DOMAIN = "DOMAIN"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    REPOSITORY = "REPOSITORY"
    OTHER = "OTHER"


class ConnectorCapabilities(BaseModel):
    """Static declaration used by the pivot engine and operator UI."""

    model_config = ConfigDict(frozen=True)

    accepted_inputs: frozenset[ConnectorInputType]
    produced_artifacts: frozenset[ProducedArtifactType]
    supports_discovery: bool = True
    supports_enrichment: bool = False
    requires_auth: bool = False
    is_external_upload: bool = False
    is_manual: bool = False
    live_supported: bool = False
    requires_network_when_live: bool = True


class CandidateProfile(BaseModel):
    """A normalized public account candidate, not a person assertion."""

    model_config = ConfigDict(extra="forbid")

    platform: str
    canonical_url: str
    platform_account_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    location: str | None = None
    employer: str | None = None
    external_links: list[str] = Field(default_factory=list)
    avatar_url: str | None = None
    source_url: str | None = None
    discovered_by: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("platform", "canonical_url")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ConnectorInput(BaseModel):
    """A seed or pivot supplied to a connector."""

    model_config = ConfigDict(extra="forbid")

    type: ConnectorInputType
    value: str
    profile: CandidateProfile | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("value")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class IdentifierArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: IdentifierType
    value: str
    normalized_value: str
    profile_url: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationArtifact(BaseModel):
    """A normalized fact with enough context to preserve provenance."""

    model_config = ConfigDict(extra="forbid")

    signal_type: str
    value: Any
    reliability: float = Field(ge=0.0, le=1.0)
    profile_url: str | None = None
    source_url: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class RelationshipArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: IdentifierType
    source_value: str
    relationship_type: str
    target_type: IdentifierType
    target_value: str
    reliability: float = Field(ge=0.0, le=1.0)
    source_url: str | None = None


class ConnectorResult(BaseModel):
    """Structured result for one connector invocation.

    ``raw_records`` contains only the connector's native payload. It is
    retained for JSONB provenance and must not be interpreted by downstream
    correlation code without a normalizer.
    """

    model_config = ConfigDict(extra="forbid")

    connector: str
    connector_version: str
    status: ConnectorRunStatus
    profiles: list[CandidateProfile] = Field(default_factory=list)
    identifiers: list[IdentifierArtifact] = Field(default_factory=list)
    observations: list[ObservationArtifact] = Field(default_factory=list)
    relationships: list[RelationshipArtifact] = Field(default_factory=list)
    raw_records: list[dict[str, Any]] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_results(self) -> bool:
        return bool(self.profiles or self.identifiers or self.observations or self.relationships)
