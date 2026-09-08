"""Convenience facade for the pure deterministic correlation pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.normalization.profiles import (
    NormalizedProfile,
    deduplicate_profiles,
)

from .candidate_generation import CandidatePair, generate_candidate_pairs
from .clustering import build_identity_hypotheses
from .features import IdentityHypothesis, PairAssessment
from .scorer import CorrelationScorer


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    profiles: tuple[NormalizedProfile, ...]
    candidate_pairs: tuple[CandidatePair, ...]
    assessments: tuple[PairAssessment, ...]
    hypotheses: tuple[IdentityHypothesis, ...]


def correlate_profiles(
    profiles: Iterable[NormalizedProfile],
    *,
    semantic_neighbors: Iterable[tuple[str, str]] = (),
    image_neighbors: Iterable[tuple[str, str]] = (),
    image_similarities: Mapping[tuple[str, str], float] | None = None,
    face_similarities: Mapping[tuple[str, str], float] | None = None,
    scorer: CorrelationScorer | None = None,
) -> CorrelationResult:
    """Run deduplication, blocking, extraction, scoring, and clustering.

    This is a synchronous CPU-only facade. Connector execution, pgvector
    nearest-neighbour queries, persistence, and job orchestration stay outside
    this package and provide their results through the explicit parameters.
    """

    # Local import avoids making the extraction package and correlation package
    # depend on each other's package initializers during module import.
    from backend.extraction import extract_pair_evidence

    normalized_profiles = deduplicate_profiles(tuple(profiles))
    candidate_pairs = generate_candidate_pairs(
        normalized_profiles,
        semantic_neighbors=semantic_neighbors,
        image_neighbors=image_neighbors,
    )
    active_scorer = scorer or CorrelationScorer()
    image_similarities = image_similarities or {}
    face_similarities = face_similarities or {}

    assessments = []
    for candidate in candidate_pairs:
        pair_key = candidate.pair_key
        evidence = extract_pair_evidence(
            candidate.left,
            candidate.right,
            image_similarity=image_similarities.get(pair_key),
            face_similarity=face_similarities.get(pair_key),
        )
        assessments.append(
            active_scorer.score(
                evidence,
                left_profile_id=candidate.left.profile_id,
                right_profile_id=candidate.right.profile_id,
            )
        )

    assessment_tuple = tuple(assessments)
    hypotheses = build_identity_hypotheses(
        normalized_profiles,
        assessment_tuple,
    )
    return CorrelationResult(
        profiles=normalized_profiles,
        candidate_pairs=candidate_pairs,
        assessments=assessment_tuple,
        hypotheses=hypotheses,
    )
