"""Biography and topic evidence extraction."""

from __future__ import annotations

import math
import re

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.names import normalize_name
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence

_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "i",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
    "developer",
    "engineer",
    "enthusiast",
}


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    # Text embedding cosine may technically be negative. Evidence strengths are
    # represented in [0, 1], so negative similarity contributes no support.
    return min(1.0, max(0.0, dot / (left_norm * right_norm)))


def lexical_bio_similarity(left: str | None, right: str | None) -> float:
    left_tokens = _bio_tokens(left)
    right_tokens = _bio_tokens(right)
    if len(left_tokens) < 3 or len(right_tokens) < 3:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def extract_bio_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    similarity = 0.0
    method = "lexical"
    reliability = 0.6
    if left.bio_embedding is not None and right.bio_embedding is not None:
        similarity = cosine_similarity(left.bio_embedding, right.bio_embedding)
        method = "embedding"
        reliability = 0.75
    elif left.bio and right.bio:
        similarity = lexical_bio_similarity(left.bio, right.bio)

    results = []
    if similarity >= 0.55:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.BIO_SIMILARITY,
                direction=Direction.SUPPORT,
                score=similarity,
                reliability=reliability,
                family=EvidenceFamily.BIO_IDENTITY,
                explanation=f"The profile biographies are similar by {method} comparison.",
                source_key=f"bio:{left.profile_id}:{right.profile_id}:{method}",
                metadata={"similarity": similarity, "method": method},
            )
        )

    shared_projects = sorted(set(left.projects) & set(right.projects))
    if shared_projects:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.PROJECT_OVERLAP,
                direction=Direction.SUPPORT,
                score=min(1.0, 0.7 + 0.1 * len(shared_projects)),
                reliability=0.85,
                family=EvidenceFamily.PROJECT_IDENTITY,
                explanation=f"Both profiles reference the project '{shared_projects[0]}'.",
                source_key=f"project:{shared_projects[0]}",
                metadata={"projects": shared_projects},
            )
        )

    shared_topics = sorted(set(left.topics) & set(right.topics))
    if len(shared_topics) >= 2:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.TOPIC_OVERLAP,
                direction=Direction.SUPPORT,
                score=min(0.7, 0.25 + 0.1 * len(shared_topics)),
                reliability=0.5,
                family=EvidenceFamily.BIO_IDENTITY,
                explanation=f"The profiles share {len(shared_topics)} public interest topics.",
                source_key=f"topics:{':'.join(shared_topics)}",
                metadata={"topics": shared_topics},
            )
        )
    return tuple(results)


def _bio_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    normalized = normalize_name(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and token not in _STOPWORDS
    }
