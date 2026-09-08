"""Conservative extraction of explicit temporal contradictions."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.profiles import NormalizedProfile, TemporalClaim

from ._shared import evidence


def extract_contradiction_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    results = []
    location_conflict = _strongest_conflict(
        left.location_claims,
        right.location_claims,
        require_exclusive=False,
    )
    if location_conflict:
        left_claim, right_claim, strength = location_conflict
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.LOCATION_CONFLICT,
                direction=Direction.CONTRADICT,
                score=strength,
                reliability=0.7 if not (left_claim.exclusive or right_claim.exclusive) else 0.9,
                family=EvidenceFamily.LOCATION_IDENTITY,
                explanation=(
                    "The profiles make different location claims during overlapping "
                    f"periods: '{left_claim.value}' and '{right_claim.value}'."
                ),
                source_key=f"location-conflict:{left_claim.normalized_value}:{right_claim.normalized_value}",
            )
        )

    # People can hold multiple affiliations. Treat overlapping organizations as
    # contradictory only when both source claims explicitly say they are
    # exclusive (for example, a sole current employer assertion).
    organization_conflict = _strongest_conflict(
        left.organization_claims,
        right.organization_claims,
        require_exclusive=True,
    )
    if organization_conflict:
        left_claim, right_claim, strength = organization_conflict
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.ORGANIZATION_CONFLICT,
                direction=Direction.CONTRADICT,
                score=strength,
                reliability=0.8,
                family=EvidenceFamily.ORGANIZATION_IDENTITY,
                explanation=(
                    "The profiles make incompatible exclusive organization claims "
                    f"during overlapping periods: '{left_claim.value}' and "
                    f"'{right_claim.value}'."
                ),
                source_key=(
                    "organization-conflict:"
                    f"{left_claim.normalized_value}:{right_claim.normalized_value}"
                ),
            )
        )
    return tuple(results)


def _strongest_conflict(
    left_claims: tuple[TemporalClaim, ...],
    right_claims: tuple[TemporalClaim, ...],
    *,
    require_exclusive: bool,
) -> tuple[TemporalClaim, TemporalClaim, float] | None:
    conflicts: list[tuple[TemporalClaim, TemporalClaim, float]] = []
    for left in left_claims:
        for right in right_claims:
            if not left.normalized_value or not right.normalized_value:
                continue
            if left.normalized_value == right.normalized_value or not left.overlaps(right):
                continue
            if require_exclusive and not (left.exclusive and right.exclusive):
                continue
            conflicts.append((left, right, left.confidence * right.confidence))
    return max(conflicts, key=lambda item: item[2]) if conflicts else None
