"""Username evidence extraction."""

from __future__ import annotations

import math

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.profiles import NormalizedProfile
from backend.normalization.usernames import username_similarity

from ._shared import evidence

_GENERIC_HANDLES = {
    "admin",
    "alex",
    "dev",
    "developer",
    "guest",
    "john",
    "johndoe",
    "root",
    "test",
    "user",
}


def username_unusualness(value: str) -> float:
    """Estimate handle distinctiveness without pretending to know population frequency.

    This heuristic is only a feature strength. A production rarity statistic can
    later replace it with observed username frequencies while preserving the
    extractor interface.
    """

    compact = "".join(character for character in value if character.isalnum())
    if not compact:
        return 0.0
    if compact in _GENERIC_HANDLES:
        return 0.25
    length_component = min(1.0, math.log2(len(compact) + 1) / 4.0)
    mixed_component = 0.08 if any(character.isdigit() for character in compact) else 0.0
    return round(min(1.0, 0.35 + 0.55 * length_component + mixed_component), 6)


def extract_username_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    if not left.normalized_username or not right.normalized_username:
        return ()

    if left.normalized_username == right.normalized_username:
        unusualness = username_unusualness(left.compact_username)
        return (
            evidence(
                left,
                right,
                signal_type=SignalType.USERNAME_EXACT,
                direction=Direction.SUPPORT,
                score=unusualness,
                reliability=0.9,
                family=EvidenceFamily.USERNAME_IDENTITY,
                explanation=(f"Both profiles use the same username '{left.normalized_username}'."),
                source_key=f"username:{left.normalized_username}",
                metadata={"unusualness": unusualness},
            ),
        )

    similarity = username_similarity(left.username, right.username)
    if similarity < 0.72:
        return ()
    return (
        evidence(
            left,
            right,
            signal_type=SignalType.USERNAME_SIMILARITY,
            direction=Direction.SUPPORT,
            score=similarity,
            reliability=0.75,
            family=EvidenceFamily.USERNAME_IDENTITY,
            explanation=(
                f"The usernames '{left.normalized_username}' and "
                f"'{right.normalized_username}' are lexically similar."
            ),
            source_key=(
                "usernames:"
                + ":".join(sorted((left.normalized_username, right.normalized_username)))
            ),
            metadata={"similarity": similarity},
        ),
    )
