"""Structured schemas for Username OSINT & Identity Discovery."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class UsernameSourceStatus(StrEnum):
    """Normalized status of a single username OSINT source execution."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class UsernameSourceResult(BaseModel):
    """Structured evidence returned by one username discovery source."""

    source_name: str
    platform: str
    category: str  # e.g., "social", "developer", "media", "gaming", "professional"
    status: UsernameSourceStatus
    account_exists: bool = False
    canonical_url: str | None = None
    display_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    location: str | None = None
    email: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
    evidence: dict[str, Any] = Field(default_factory=dict)
    response_time_ms: float = 0.0
    message: str | None = None


class UsernameOSINTResult(BaseModel):
    """Complete aggregated Username OSINT discovery result."""

    username: str
    normalized_username: str
    sources_checked: int = 0
    accounts_found: int = 0
    source_results: list[UsernameSourceResult] = Field(default_factory=list)
    overall_confidence: float = 0.0
    scan_duration_ms: float = 0.0
    display_names_found: list[str] = Field(default_factory=list)
    emails_found: list[str] = Field(default_factory=list)
    locations_found: list[str] = Field(default_factory=list)
    bios_found: list[str] = Field(default_factory=list)
    avatar_urls: list[str] = Field(default_factory=list)
    platform_categories: dict[str, int] = Field(default_factory=dict)
