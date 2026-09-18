"""Identifier-based evidence extraction across profiles."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, EvidenceSignal, SignalType
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def extract_identifier_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple[EvidenceSignal, ...]:
    """Extract explicit evidence signals based on shared first-class identifiers.
    
    Correlates Profile A -> Identifier X -> Profile B without requiring
    the identifier to become a full profile.
    """
    signals: list[EvidenceSignal] = []

    # 1. Exact email match (from bio or extracted claims)
    left_emails = set(getattr(left, "emails", ()))
    right_emails = set(getattr(right, "emails", ()))
    common_emails = left_emails.intersection(right_emails)
    for email in sorted(common_emails):
        signals.append(
            evidence(
                left,
                right,
                signal_type=SignalType.EMAIL_EXACT,
                direction=Direction.SUPPORT,
                score=0.95,
                reliability=0.95,
                family=EvidenceFamily.IDENTIFIER_IDENTITY,
                explanation=f"Profiles share the exact same public email identifier '{email}'.",
                source_key=f"email:{email}",
                metadata={"identifier_type": "EMAIL", "identifier_value": email},
            )
        )

    # 2. Exact domain match
    common_domains = set(left.personal_domains).intersection(set(right.personal_domains))
    for domain in sorted(common_domains):
        signals.append(
            evidence(
                left,
                right,
                signal_type=SignalType.DOMAIN_EXACT,
                direction=Direction.SUPPORT,
                score=0.88,
                reliability=0.90,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation=f"Profiles share the exact same personal domain identifier '{domain}'.",
                source_key=f"domain:{domain}",
                metadata={"identifier_type": "DOMAIN", "identifier_value": domain},
            )
        )

    # 3. Exact URL match (external links)
    common_urls = set(left.external_links).intersection(set(right.external_links))
    for url in sorted(common_urls):
        signals.append(
            evidence(
                left,
                right,
                signal_type=SignalType.URL_EXACT,
                direction=Direction.SUPPORT,
                score=0.85,
                reliability=0.88,
                family=EvidenceFamily.WEB_IDENTITY,
                explanation=f"Profiles share the exact same public URL identifier '{url}'.",
                source_key=f"url:{url}",
                metadata={"identifier_type": "URL", "identifier_value": url},
            )
        )

    # 4. Project / Repository overlap as explicit repository relationship
    common_projects = set(left.projects).intersection(set(right.projects))
    for project in sorted(common_projects):
        signals.append(
            evidence(
                left,
                right,
                signal_type=SignalType.REPOSITORY_RELATIONSHIP,
                direction=Direction.SUPPORT,
                score=0.80,
                reliability=0.85,
                family=EvidenceFamily.PROJECT_IDENTITY,
                explanation=f"Profiles share repository/project reference '{project}'.",
                source_key=f"repository:{project}",
                metadata={"identifier_type": "REPOSITORY", "identifier_value": project},
            )
        )

    return tuple(signals)
