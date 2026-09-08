"""Display-name evidence extraction."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.names import name_similarity, name_tokens
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def extract_name_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> tuple:
    if not left.normalized_display_name or not right.normalized_display_name:
        return ()
    similarity = name_similarity(left.display_name, right.display_name)
    if similarity < 0.72:
        return ()

    # A single common first name is weak evidence. Multi-token/exact names are
    # somewhat more informative, while still never acting as a merge anchor.
    shared_tokens = set(name_tokens(left.display_name)) & set(name_tokens(right.display_name))
    informativeness = min(1.0, 0.45 + 0.2 * len(shared_tokens))
    strength = similarity * informativeness
    return (
        evidence(
            left,
            right,
            signal_type=SignalType.DISPLAY_NAME_SIMILARITY,
            direction=Direction.SUPPORT,
            score=strength,
            reliability=0.75,
            family=EvidenceFamily.NAME_IDENTITY,
            explanation=(
                f"Display names '{left.display_name}' and '{right.display_name}' "
                "normalize to similar name forms."
            ),
            source_key=(
                "names:"
                + ":".join(sorted((left.normalized_display_name, right.normalized_display_name)))
            ),
            metadata={"lexical_similarity": similarity},
        ),
    )
