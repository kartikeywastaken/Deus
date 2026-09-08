"""Organization and current-location supporting evidence."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.names import name_similarity
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def extract_organization_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    results = []
    if left.normalized_organization and right.normalized_organization:
        similarity = name_similarity(left.organization, right.organization)
        if similarity >= 0.9:
            results.append(
                evidence(
                    left,
                    right,
                    signal_type=SignalType.ORGANIZATION_OVERLAP,
                    direction=Direction.SUPPORT,
                    score=similarity,
                    reliability=0.75,
                    family=EvidenceFamily.ORGANIZATION_IDENTITY,
                    explanation=(f"Both profiles claim the organization '{left.organization}'."),
                    source_key=f"organization:{left.normalized_organization}",
                    metadata={"similarity": similarity},
                )
            )

    if (
        left.normalized_location
        and right.normalized_location
        and left.normalized_location == right.normalized_location
    ):
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.LOCATION_OVERLAP,
                direction=Direction.SUPPORT,
                score=0.7,
                reliability=0.65,
                family=EvidenceFamily.LOCATION_IDENTITY,
                explanation=f"Both profiles claim the location '{left.location}'.",
                source_key=f"location:{left.normalized_location}",
            )
        )
    return tuple(results)
