"""Stable data-transfer values returned by persistence repositories.

The correlation engine should not need an open SQLAlchemy session.  These
snapshots therefore collect the relational profile fields together with the
search-scoped facts kept in observation JSONB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from backend.db.models import ConnectorRun, Profile, ProfileObservation


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """Bounded-work limits captured when an investigation is created."""

    max_pivot_depth: int = 3
    max_questions: int = 3
    max_connector_runs: int = 30
    max_candidates: int = 100
    max_search_duration_seconds: int = 600


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """A detached profile plus search-scoped enrichment fields."""

    id: UUID
    platform: str
    canonical_url: str
    platform_account_id: str | None = None
    username: str | None = None
    normalized_username: str = ""
    display_name: str | None = None
    normalized_display_name: str = ""
    bio: str | None = None
    location: str | None = None
    organization: str | None = None
    avatar_url: str | None = None
    external_links: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    discovered_by: tuple[str, ...] = ()
    source_observation_ids: tuple[str, ...] = ()

    @property
    def profile_id(self) -> str:
        """Expose the name expected by the database-independent normalizer."""

        return str(self.id)


@dataclass(frozen=True, slots=True)
class PersistedConnectorResult:
    """Objects materialized from a normalized connector result."""

    connector_run: ConnectorRun
    profiles: tuple[Profile, ...]
    observations: tuple[ProfileObservation, ...]


@dataclass(frozen=True, slots=True)
class QuestionAnswerResult:
    """The answered question and its newly persisted answer record."""

    question: Any
    answer: Any
