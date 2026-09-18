"""Deterministic evidence extraction from normalized public profiles."""

from __future__ import annotations

from backend.correlation.features import EvidenceSignal
from backend.normalization.profiles import NormalizedProfile

from .bios import extract_bio_evidence
from .contradictions import extract_contradiction_evidence
from .domains import extract_domain_evidence
from .identifiers import extract_identifier_evidence
from .images import extract_image_evidence
from .links import extract_link_evidence
from .names import extract_name_evidence
from .organizations import extract_organization_evidence
from .usernames import extract_username_evidence


def extract_pair_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
    *,
    image_similarity: float | None = None,
    face_similarity: float | None = None,
) -> tuple[EvidenceSignal, ...]:
    """Extract all currently supported deterministic pairwise evidence."""

    evidence: list[EvidenceSignal] = []
    extractors = (
        extract_identifier_evidence,
        extract_username_evidence,
        extract_name_evidence,
        extract_link_evidence,
        extract_domain_evidence,
        extract_bio_evidence,
        extract_organization_evidence,
        extract_contradiction_evidence,
    )
    for extractor in extractors:
        evidence.extend(extractor(left, right))
    evidence.extend(
        extract_image_evidence(
            left,
            right,
            image_similarity=image_similarity,
            face_similarity=face_similarity,
        )
    )
    return tuple(evidence)


__all__ = ["extract_pair_evidence", "extract_identifier_evidence"]
