"""Small helpers shared by deterministic evidence extractors."""

from __future__ import annotations

from backend.correlation.features import (
    Direction,
    EvidenceFamily,
    EvidenceSignal,
    SignalType,
)
from backend.normalization.profiles import NormalizedProfile


def evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
    *,
    signal_type: SignalType,
    direction: Direction,
    score: float,
    reliability: float,
    family: EvidenceFamily,
    explanation: str,
    source_key: str | None = None,
    metadata: dict[str, object] | None = None,
) -> EvidenceSignal:
    return EvidenceSignal(
        left_profile_id=left.profile_id,
        right_profile_id=right.profile_id,
        signal_type=signal_type,
        direction=direction,
        normalized_score=min(1.0, max(0.0, score)),
        reliability=min(1.0, max(0.0, reliability)),
        evidence_family=family,
        explanation=explanation,
        source_observation_ids=tuple(
            dict.fromkeys(left.source_observation_ids + right.source_observation_ids)
        ),
        source_key=source_key,
        metadata=metadata or {},
    )
