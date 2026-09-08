from __future__ import annotations

from backend.correlation.clustering import build_identity_hypotheses
from backend.correlation.features import (
    Classification,
    Direction,
    EvidenceFamily,
    EvidenceSignal,
    SignalType,
)
from backend.correlation.scorer import score_evidence


def _assessment(left: str, right: str, classification: Classification):
    if classification is Classification.STRONG:
        signals = [
            _signal(left, right, SignalType.DIRECT_PROFILE_LINK, EvidenceFamily.WEB_IDENTITY),
            _signal(left, right, SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY),
        ]
    elif classification is Classification.LIKELY:
        signals = [
            _signal(left, right, SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY),
            _signal(
                left,
                right,
                SignalType.DISPLAY_NAME_SIMILARITY,
                EvidenceFamily.NAME_IDENTITY,
            ),
        ]
    elif classification is Classification.CONTRADICTORY:
        signals = [
            _signal(
                left,
                right,
                SignalType.DIFFERENT_FACE,
                EvidenceFamily.IMAGE_IDENTITY,
                direction=Direction.CONTRADICT,
            )
        ]
    else:
        signals = [
            _signal(left, right, SignalType.USERNAME_EXACT, EvidenceFamily.USERNAME_IDENTITY)
        ]
    assessment = score_evidence(signals)
    assert assessment.classification is classification
    return assessment


def _signal(
    left: str,
    right: str,
    signal_type: SignalType,
    family: EvidenceFamily,
    *,
    direction: Direction = Direction.SUPPORT,
) -> EvidenceSignal:
    return EvidenceSignal(
        left_profile_id=left,
        right_profile_id=right,
        signal_type=signal_type,
        direction=direction,
        normalized_score=1.0,
        reliability=1.0,
        evidence_family=family,
        explanation="test",
    )


def test_complete_link_evidence_forms_one_hypothesis() -> None:
    assessments = [
        _assessment("a", "b", Classification.STRONG),
        _assessment("a", "c", Classification.LIKELY),
        _assessment("b", "c", Classification.LIKELY),
    ]

    hypotheses = build_identity_hypotheses(("a", "b", "c"), assessments)

    assert len(hypotheses) == 1
    assert hypotheses[0].profile_ids == ("a", "b", "c")
    assert hypotheses[0].classification is Classification.LIKELY


def test_clustering_does_not_blindly_apply_transitivity() -> None:
    assessments = [
        _assessment("a", "b", Classification.STRONG),
        _assessment("b", "c", Classification.STRONG),
        _assessment("a", "c", Classification.AMBIGUOUS),
    ]

    hypotheses = build_identity_hypotheses(("a", "b", "c"), assessments)

    assert sorted(len(hypothesis.profile_ids) for hypothesis in hypotheses) == [1, 2]
    assert all(len(hypothesis.profile_ids) < 3 for hypothesis in hypotheses)


def test_missing_cross_pair_also_prevents_transitive_merge() -> None:
    assessments = [
        _assessment("a", "b", Classification.LIKELY),
        _assessment("b", "c", Classification.LIKELY),
    ]

    hypotheses = build_identity_hypotheses(("a", "b", "c"), assessments)

    assert sorted(len(item.profile_ids) for item in hypotheses) == [1, 2]


def test_contradictory_profile_remains_an_alternative() -> None:
    hypotheses = build_identity_hypotheses(
        ("a", "b", "c"),
        [
            _assessment("a", "b", Classification.LIKELY),
            _assessment("a", "c", Classification.CONTRADICTORY),
            _assessment("b", "c", Classification.CONTRADICTORY),
        ],
    )

    assert hypotheses[0].profile_ids == ("a", "b")
    assert hypotheses[1].profile_ids == ("c",)
