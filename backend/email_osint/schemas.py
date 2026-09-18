"""Structured schemas for Email OSINT & Identity Discovery."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EmailSourceStatus(StrEnum):
    """Normalized status of a single email OSINT source execution."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class EmailProviderType(StrEnum):
    GMAIL = "GMAIL"
    OUTLOOK = "OUTLOOK"
    PROTON = "PROTON"
    ICLOUD = "ICLOUD"
    YAHOO = "YAHOO"
    ZOIC = "ZOIC"
    CUSTOM_CORPORATE = "CUSTOM_CORPORATE"
    UNKNOWN = "UNKNOWN"


class DiscoveredIdentifier(BaseModel):
    """An identifier extracted from an email check or secondary profile."""

    model_config = ConfigDict(extra="forbid")

    type: str  # username, profile_url, display_name, domain, alias, email, avatar_url
    value: str
    normalized_value: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmailDomainIntel(BaseModel):
    """Passive domain intelligence extracted from the email domain."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    provider_name: str = "Unknown"
    provider_type: EmailProviderType = EmailProviderType.UNKNOWN
    mx_records: list[str] = Field(default_factory=list)
    txt_records: list[str] = Field(default_factory=list)
    is_disposable: bool = False
    is_free_provider: bool = False
    organization_hint: str | None = None


class EmailSourceResult(BaseModel):
    """Structured evidence returned by one source adapter."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    category: str  # e.g., "social", "developer", "google", "breach", "domain"
    status: EmailSourceStatus
    account_exists: bool = False
    canonical_url: str | None = None
    display_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    identifiers: list[DiscoveredIdentifier] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    response_time_ms: float = 0.0
    message: str | None = None


class EmailOSINTResult(BaseModel):
    """Complete aggregated Email OSINT discovery result."""

    model_config = ConfigDict(extra="forbid")

    email: str
    normalized_email: str
    domain_intel: EmailDomainIntel
    sources_checked: int = 0
    accounts_found: int = 0
    source_results: list[EmailSourceResult] = Field(default_factory=list)
    discovered_identifiers: list[DiscoveredIdentifier] = Field(default_factory=list)
    pivoted_profiles: list[dict[str, Any]] = Field(default_factory=list)
    overall_confidence: float = 0.0
    scan_duration_ms: float = 0.0
