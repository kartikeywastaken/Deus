"""Rank identity hypotheses for relevance to the supplied search seed."""

from __future__ import annotations

from dataclasses import replace

from backend.core.enums import SeedType
from backend.correlation import Classification, IdentityHypothesis, IdentityMembership
from backend.normalization.profiles import NormalizedProfile
from backend.normalization.usernames import username_similarity


def rank_hypotheses_for_seed(
    hypotheses: tuple[IdentityHypothesis, ...],
    profiles: tuple[NormalizedProfile, ...],
    *,
    seed_type: SeedType,
    seed_value: str,
) -> tuple[IdentityHypothesis, ...]:
    """Combine cluster coherence with transparent seed relevance.

    Correlation answers whether accounts plausibly belong together. Search
    ranking additionally asks whether each resulting cluster resembles the
    supplied target seed. Keeping this step separate prevents a singleton from
    being declared irrelevant merely because it has no second account to pair
    with, while still never merging on username alone.
    """

    if seed_type is not SeedType.USERNAME:
        return hypotheses

    profiles_by_id = {profile.profile_id: profile for profile in profiles}
    reranked: list[IdentityHypothesis] = []
    for hypothesis in hypotheses:
        updated_memberships: list[IdentityMembership] = []
        affinities: list[float] = []
        for membership in hypothesis.memberships:
            profile = profiles_by_id[membership.profile_id]
            affinity = username_similarity(seed_value, profile.username)
            affinities.append(affinity)
            target_score = max(membership.score, round(0.85 * affinity, 6))
            updated_memberships.append(
                replace(
                    membership,
                    score=target_score,
                    classification=_classify_relevance(target_score),
                )
            )

        seed_relevance = round(0.85 * max(affinities, default=0.0), 6)
        overall_score = max(hypothesis.overall_score, seed_relevance)
        reranked.append(
            replace(
                hypothesis,
                memberships=tuple(updated_memberships),
                overall_score=overall_score,
                classification=_classify_relevance(overall_score),
            )
        )

    reranked.sort(
        key=lambda item: (item.overall_score, len(item.profile_ids), item.hypothesis_id),
        reverse=True,
    )
    return tuple(
        replace(hypothesis, rank=rank) for rank, hypothesis in enumerate(reranked, start=1)
    )


def _classify_relevance(score: float) -> Classification:
    if score >= 0.70:
        return Classification.STRONG
    if score >= 0.45:
        return Classification.LIKELY
    if score >= 0.25:
        return Classification.AMBIGUOUS
    if score < 0:
        return Classification.CONTRADICTORY
    return Classification.WEAK
