from __future__ import annotations

from backend.correlation.features import (
    Classification,
    Direction,
    EvidenceFamily,
    EvidenceSignal,
    SignalType,
)
from backend.correlation.scorer import score_evidence


def _signal(
    signal_type: SignalType,
    family: EvidenceFamily,
    *,
    direction: Direction = Direction.SUPPORT,
    score: float = 1.0,
    reliability: float = 1.0,
) -> EvidenceSignal:
    return EvidenceSignal(
        left_profile_id="left",
        right_profile_id="right",
        signal_type=signal_type,
        direction=direction,
        normalized_score=score,
        reliability=reliability,
        evidence_family=family,
        explanation=f"Test evidence: {signal_type}",
    )


def test_username_alone_never_becomes_likely_identity() -> None:
    assessment = score_evidence(
        [_signal(SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY)]
    )

    assert assessment.raw_score == 20.0
    assert assessment.classification is Classification.AMBIGUOUS
    assert assessment.support_family_count == 1


def test_multiple_independent_families_can_form_strong_assessment() -> None:
    assessment = score_evidence(
        [
            _signal(SignalType.DIRECT_PROFILE_LINK, EvidenceFamily.WEB_IDENTITY),
            _signal(SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY),
            _signal(
                SignalType.DISPLAY_NAME_SIMILARITY,
                EvidenceFamily.NAME_IDENTITY,
            ),
        ]
    )

    assert assessment.raw_score == 70.0
    assert assessment.normalized_score == 0.7
    assert assessment.classification is Classification.STRONG


def test_image_family_signals_are_deduplicated() -> None:
    assessment = score_evidence(
        [
            _signal(SignalType.EXACT_AVATAR, EvidenceFamily.IMAGE_IDENTITY),
            _signal(SignalType.IMAGE_SIMILARITY, EvidenceFamily.IMAGE_IDENTITY),
            _signal(SignalType.FACE_SIMILARITY, EvidenceFamily.IMAGE_IDENTITY),
        ]
    )

    assert assessment.raw_score == 20.0
    assert len(assessment.selected_evidence) == 1
    assert assessment.selected_evidence[0].signal_type is SignalType.EXACT_AVATAR


def test_negative_evidence_decreases_score_and_can_be_contradictory() -> None:
    positive = _signal(SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY)
    base = score_evidence([positive])
    contradicted = score_evidence(
        [
            positive,
            _signal(
                SignalType.DIFFERENT_FACE,
                EvidenceFamily.IMAGE_IDENTITY,
                direction=Direction.CONTRADICT,
            ),
        ]
    )

    assert contradicted.raw_score < base.raw_score
    assert contradicted.raw_score == -20.0
    assert contradicted.classification is Classification.CONTRADICTORY
    assert contradicted.contradiction_family_count == 1


def test_equal_strength_family_tie_is_resolved_conservatively() -> None:
    assessment = score_evidence(
        [
            _signal(SignalType.EXACT_AVATAR, EvidenceFamily.IMAGE_IDENTITY),
            _signal(
                SignalType.PERSONAL_DOMAIN_CONFLICT,
                EvidenceFamily.IMAGE_IDENTITY,
                direction=Direction.CONTRADICT,
            ),
        ]
    )

    assert assessment.raw_score == -20.0
    assert assessment.selected_evidence[0].direction is Direction.CONTRADICT


def test_empty_evidence_is_weak_when_pair_is_explicit() -> None:
    assessment = score_evidence([], left_profile_id="left", right_profile_id="right")
    assert assessment.raw_score == 0.0
    assert assessment.classification is Classification.WEAK
