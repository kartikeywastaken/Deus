"""Direct and shared web-link evidence extraction."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def extract_link_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    results = []
    left_links = set(left.external_links)
    right_links = set(right.external_links)

    directions: list[str] = []
    if right.canonical_url in left_links:
        directions.append(f"{left.platform} links directly to {right.platform}")
    if left.canonical_url in right_links:
        directions.append(f"{right.platform} links directly to {left.platform}")
    if directions:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.DIRECT_PROFILE_LINK,
                direction=Direction.SUPPORT,
                score=1.0,
                reliability=0.98,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation="; ".join(directions) + ".",
                source_key=(
                    "direct-link:" + ":".join(sorted((left.canonical_url, right.canonical_url)))
                ),
            )
        )

    shared = sorted((left_links & right_links) - {left.canonical_url, right.canonical_url})
    if shared:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.SHARED_EXTERNAL_URL,
                direction=Direction.SUPPORT,
                score=1.0 if len(shared) > 1 else 0.85,
                reliability=0.9,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation=f"Both profiles link to {shared[0]}",
                source_key=f"shared-url:{shared[0]}",
                metadata={"urls": shared},
            )
        )
    return tuple(results)
