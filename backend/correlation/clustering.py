"""Conservative complete-link identity hypothesis construction."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from itertools import combinations

from backend.normalization.profiles import NormalizedProfile

from .features import (
    Classification,
    IdentityHypothesis,
    IdentityMembership,
    PairAssessment,
)


def build_identity_hypotheses(
    profiles: Iterable[NormalizedProfile | str],
    assessments: Iterable[PairAssessment],
    *,
    minimum_merge_classification: Classification = Classification.LIKELY,
) -> tuple[IdentityHypothesis, ...]:
    """Build non-overlapping hypotheses without assuming transitivity.

    Two clusters merge only when *every* cross-cluster pair has an assessment
    at or above ``minimum_merge_classification``. Thus A↔B and B↔C do not imply
    A↔C; missing, weak, or contradictory A↔C evidence keeps C separate.
    """

    profile_ids = tuple(_profile_id(profile) for profile in profiles)
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("profile IDs must be unique before clustering")

    assessment_by_pair: dict[tuple[str, str], PairAssessment] = {}
    for assessment in assessments:
        if assessment.pair_key in assessment_by_pair:
            raise ValueError(f"duplicate assessment for pair {assessment.pair_key}")
        assessment_by_pair[assessment.pair_key] = assessment

    clusters: list[set[str]] = [{profile_id} for profile_id in sorted(profile_ids)]
    eligible = sorted(
        assessment_by_pair.values(),
        key=lambda assessment: (
            assessment.classification.merge_rank,
            assessment.raw_score,
            assessment.pair_key,
        ),
        reverse=True,
    )

    for assessment in eligible:
        if assessment.classification.merge_rank < minimum_merge_classification.merge_rank:
            continue
        left_cluster = _find_cluster(clusters, assessment.left_profile_id)
        right_cluster = _find_cluster(clusters, assessment.right_profile_id)
        if left_cluster is None or right_cluster is None or left_cluster is right_cluster:
            continue
        if _can_merge(
            left_cluster,
            right_cluster,
            assessment_by_pair,
            minimum_merge_classification,
        ):
            left_cluster.update(right_cluster)
            clusters.remove(right_cluster)

    hypotheses = [_make_hypothesis(cluster, assessment_by_pair) for cluster in clusters]
    hypotheses.sort(
        key=lambda hypothesis: (
            len(hypothesis.profile_ids),
            hypothesis.overall_score,
            hypothesis.hypothesis_id,
        ),
        reverse=True,
    )
    return tuple(
        IdentityHypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            rank=rank,
            profile_ids=hypothesis.profile_ids,
            memberships=hypothesis.memberships,
            overall_score=hypothesis.overall_score,
            classification=hypothesis.classification,
            supporting_pair_keys=hypothesis.supporting_pair_keys,
        )
        for rank, hypothesis in enumerate(hypotheses, start=1)
    )


def _can_merge(
    left_cluster: set[str],
    right_cluster: set[str],
    assessment_by_pair: dict[tuple[str, str], PairAssessment],
    minimum: Classification,
) -> bool:
    for left_id in left_cluster:
        for right_id in right_cluster:
            assessment = assessment_by_pair.get(_pair_key(left_id, right_id))
            if (
                assessment is None
                or assessment.classification.merge_rank < minimum.merge_rank
                or assessment.classification is Classification.CONTRADICTORY
            ):
                return False
    return True


def _make_hypothesis(
    cluster: set[str],
    assessment_by_pair: dict[tuple[str, str], PairAssessment],
) -> IdentityHypothesis:
    profile_ids = tuple(sorted(cluster))
    pair_keys = tuple(_pair_key(left, right) for left, right in combinations(profile_ids, 2))
    pair_assessments = tuple(assessment_by_pair[key] for key in pair_keys)

    if not pair_assessments:
        classification = Classification.WEAK
        overall_score = 0.0
    else:
        weakest = min(
            pair_assessments,
            key=lambda assessment: (
                assessment.classification.merge_rank,
                assessment.normalized_score,
            ),
        )
        classification = weakest.classification
        overall_score = round(min(item.normalized_score for item in pair_assessments), 6)

    memberships = []
    for profile_id in profile_ids:
        related = tuple(
            assessment for assessment in pair_assessments if profile_id in assessment.pair_key
        )
        if not related:
            memberships.append(
                IdentityMembership(
                    profile_id=profile_id,
                    score=0.0,
                    classification=Classification.WEAK,
                    support_count=0,
                    contradiction_count=0,
                )
            )
            continue
        weakest = min(
            related,
            key=lambda assessment: (
                assessment.classification.merge_rank,
                assessment.normalized_score,
            ),
        )
        memberships.append(
            IdentityMembership(
                profile_id=profile_id,
                score=round(min(item.normalized_score for item in related), 6),
                classification=weakest.classification,
                support_count=sum(item.support_family_count for item in related),
                contradiction_count=sum(item.contradiction_family_count for item in related),
            )
        )

    digest = hashlib.sha256("\x00".join(profile_ids).encode()).hexdigest()[:16]
    return IdentityHypothesis(
        hypothesis_id=f"hypothesis-{digest}",
        rank=0,
        profile_ids=profile_ids,
        memberships=tuple(memberships),
        overall_score=overall_score,
        classification=classification,
        supporting_pair_keys=pair_keys,
    )


def _find_cluster(clusters: list[set[str]], profile_id: str) -> set[str] | None:
    return next((cluster for cluster in clusters if profile_id in cluster), None)


def _profile_id(profile: NormalizedProfile | str) -> str:
    return profile if isinstance(profile, str) else profile.profile_id


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))  # type: ignore[return-value]
