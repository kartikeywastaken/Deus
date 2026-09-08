"""Typed values shared by evidence extraction, scoring, and clustering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Direction(StrEnum):
    SUPPORT = "SUPPORT"
    CONTRADICT = "CONTRADICT"
    NEUTRAL = "NEUTRAL"


class EvidenceFamily(StrEnum):
    WEB_IDENTITY = "WEB_IDENTITY"
    USERNAME_IDENTITY = "USERNAME_IDENTITY"
    NAME_IDENTITY = "NAME_IDENTITY"
    BIO_IDENTITY = "BIO_IDENTITY"
    ORGANIZATION_IDENTITY = "ORGANIZATION_IDENTITY"
    LOCATION_IDENTITY = "LOCATION_IDENTITY"
    PROJECT_IDENTITY = "PROJECT_IDENTITY"
    IMAGE_IDENTITY = "IMAGE_IDENTITY"


class SignalType(StrEnum):
    DIRECT_PROFILE_LINK = "DIRECT_PROFILE_LINK"
    SHARED_PERSONAL_DOMAIN = "SHARED_PERSONAL_DOMAIN"
    SHARED_EXTERNAL_URL = "SHARED_EXTERNAL_URL"
    PERSONAL_DOMAIN_CONFLICT = "PERSONAL_DOMAIN_CONFLICT"
    EXPLICIT_IDENTITY_CONFLICT = "EXPLICIT_IDENTITY_CONFLICT"

    USERNAME_EXACT = "USERNAME_EXACT"
    USERNAME_SIMILARITY = "USERNAME_SIMILARITY"
    DISPLAY_NAME_SIMILARITY = "DISPLAY_NAME_SIMILARITY"

    BIO_SIMILARITY = "BIO_SIMILARITY"
    BIOGRAPHICAL_CONTRADICTION = "BIOGRAPHICAL_CONTRADICTION"
    ORGANIZATION_OVERLAP = "ORGANIZATION_OVERLAP"
    ORGANIZATION_CONFLICT = "ORGANIZATION_CONFLICT"
    LOCATION_OVERLAP = "LOCATION_OVERLAP"
    LOCATION_CONFLICT = "LOCATION_CONFLICT"
    PROJECT_OVERLAP = "PROJECT_OVERLAP"
    TOPIC_OVERLAP = "TOPIC_OVERLAP"

    EXACT_AVATAR = "EXACT_AVATAR"
    IMAGE_SIMILARITY = "IMAGE_SIMILARITY"
    FACE_SIMILARITY = "FACE_SIMILARITY"
    DIFFERENT_FACE = "DIFFERENT_FACE"


class Classification(StrEnum):
    STRONG = "STRONG"
    LIKELY = "LIKELY"
    AMBIGUOUS = "AMBIGUOUS"
    WEAK = "WEAK"
    CONTRADICTORY = "CONTRADICTORY"

    @property
    def merge_rank(self) -> int:
        """Higher is safer to use as identity-hypothesis merge evidence."""

        return {
            Classification.CONTRADICTORY: 0,
            Classification.WEAK: 1,
            Classification.AMBIGUOUS: 2,
            Classification.LIKELY: 3,
            Classification.STRONG: 4,
        }[self]


class BlockingReason(StrEnum):
    EXACT_USERNAME = "EXACT_USERNAME"
    SIMILAR_USERNAME = "SIMILAR_USERNAME"
    SIMILAR_NAME = "SIMILAR_NAME"
    SHARED_DOMAIN = "SHARED_DOMAIN"
    SHARED_EXTERNAL_URL = "SHARED_EXTERNAL_URL"
    DIRECT_CROSS_LINK = "DIRECT_CROSS_LINK"
    ORGANIZATION_AND_NAME = "ORGANIZATION_AND_NAME"
    LOCATION_AND_NAME = "LOCATION_AND_NAME"
    SHARED_AVATAR = "SHARED_AVATAR"
    SIMILAR_BIO = "SIMILAR_BIO"
    SEMANTIC_NEIGHBOR = "SEMANTIC_NEIGHBOR"
    IMAGE_NEIGHBOR = "IMAGE_NEIGHBOR"


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    """One explainable, directional fact about a profile pair."""

    left_profile_id: str
    right_profile_id: str
    signal_type: SignalType
    direction: Direction
    normalized_score: float
    reliability: float
    evidence_family: EvidenceFamily
    explanation: str
    source_observation_ids: tuple[str, ...] = ()
    source_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized_score <= 1.0:
            raise ValueError("normalized_score must be between 0 and 1")
        if not 0.0 <= self.reliability <= 1.0:
            raise ValueError("reliability must be between 0 and 1")
        if self.left_profile_id == self.right_profile_id:
            raise ValueError("evidence must compare two different profiles")
        if not self.explanation.strip():
            raise ValueError("evidence requires an explanation")
        # Copy caller-owned dictionaries so an immutable evidence object cannot
        # be changed indirectly after it has been scored.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def pair_key(self) -> tuple[str, str]:
        return tuple(sorted((self.left_profile_id, self.right_profile_id)))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class EvidenceContribution:
    evidence: EvidenceSignal
    weighted_score: float


@dataclass(frozen=True, slots=True)
class PairAssessment:
    """Transparent result from the uncalibrated V0 scoring model."""

    left_profile_id: str
    right_profile_id: str
    raw_score: float
    normalized_score: float
    classification: Classification
    evidence: tuple[EvidenceSignal, ...]
    selected_evidence: tuple[EvidenceSignal, ...]
    contributions: tuple[EvidenceContribution, ...]
    support_family_count: int
    contradiction_family_count: int
    model_version: str

    @property
    def pair_key(self) -> tuple[str, str]:
        return tuple(sorted((self.left_profile_id, self.right_profile_id)))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class IdentityMembership:
    profile_id: str
    score: float
    classification: Classification
    support_count: int
    contradiction_count: int


@dataclass(frozen=True, slots=True)
class IdentityHypothesis:
    hypothesis_id: str
    rank: int
    profile_ids: tuple[str, ...]
    memberships: tuple[IdentityMembership, ...]
    overall_score: float
    classification: Classification
    supporting_pair_keys: tuple[tuple[str, str], ...]
