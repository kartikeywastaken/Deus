"""Personal-domain evidence extraction."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def extract_domain_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    results = []
    shared = sorted(set(left.personal_domains) & set(right.personal_domains))
    if shared:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.SHARED_PERSONAL_DOMAIN,
                direction=Direction.SUPPORT,
                score=1.0,
                reliability=0.95,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation=f"Both profiles link to the personal domain {shared[0]}.",
                source_key=f"domain:{shared[0]}",
                metadata={"domains": shared},
            )
        )

    # Multiple personal sites are common, so a conflict is emitted only when
    # both connector records explicitly mark different domains as primary.
    if left.primary_domain and right.primary_domain and left.primary_domain != right.primary_domain:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.PERSONAL_DOMAIN_CONFLICT,
                direction=Direction.CONTRADICT,
                score=0.8,
                reliability=0.8,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation=(
                    "The profiles explicitly claim different primary personal domains: "
                    f"{left.primary_domain} and {right.primary_domain}."
                ),
                source_key=(
                    "primary-domain-conflict:"
                    + ":".join(sorted((left.primary_domain, right.primary_domain)))
                ),
            )
        )
    return tuple(results)
