from __future__ import annotations

from backend.correlation.features import Direction, SignalType
from backend.extraction import extract_pair_evidence
from backend.normalization.profiles import normalize_profile


def _profile(profile_id: str, platform: str, **extra):
    return normalize_profile(
        {
            "id": profile_id,
            "platform": platform,
            "canonical_url": f"https://{platform}.example/{profile_id}",
            **extra,
        }
    )


def test_extracts_public_supporting_evidence_with_provenance() -> None:
    left = _profile(
        "left",
        "github",
        username="alice_dev",
        display_name="Alice Doe",
        external_links=["https://alice.dev", "https://reddit.example/right"],
        source_observation_ids=["obs-github"],
    )
    right = _profile(
        "right",
        "reddit",
        username="alice-dev",
        display_name="Alice Doe",
        external_links=["https://alice.dev"],
        source_observation_ids=["obs-reddit"],
    )

    signals = extract_pair_evidence(left, right)
    signal_types = {signal.signal_type for signal in signals}

    assert SignalType.DIRECT_PROFILE_LINK in signal_types
    assert SignalType.SHARED_PERSONAL_DOMAIN in signal_types
    assert SignalType.USERNAME_SIMILARITY in signal_types
    assert all(
        signal.source_observation_ids == ("obs-github", "obs-reddit")
        for signal in signals
    )


def test_temporally_overlapping_location_claims_can_contradict() -> None:
    left = _profile(
        "left",
        "github",
        location_claims=[
            {"value": "Delhi", "start": "2024-01-01", "end": "2024-12-31"}
        ],
    )
    right = _profile(
        "right",
        "reddit",
        location_claims=[
            {"value": "Mumbai", "start": "2024-06-01", "end": "2025-01-01"}
        ],
    )

    signals = extract_pair_evidence(left, right)

    conflict = next(item for item in signals if item.signal_type is SignalType.LOCATION_CONFLICT)
    assert conflict.direction is Direction.CONTRADICT


def test_non_overlapping_location_history_is_not_a_contradiction() -> None:
    left = _profile(
        "left",
        "github",
        location_claims=[
            {"value": "Delhi", "start": "2020-01-01", "end": "2021-01-01"}
        ],
    )
    right = _profile(
        "right",
        "reddit",
        location_claims=[
            {"value": "Mumbai", "start": "2023-01-01", "end": "2024-01-01"}
        ],
    )

    assert SignalType.LOCATION_CONFLICT not in {
        item.signal_type for item in extract_pair_evidence(left, right)
    }


def test_face_similarity_is_supporting_evidence_not_a_special_identity_result() -> None:
    left = _profile("left", "github")
    right = _profile("right", "reddit")

    signals = extract_pair_evidence(left, right, face_similarity=0.9)

    assert len(signals) == 1
    assert signals[0].signal_type is SignalType.FACE_SIMILARITY
    assert signals[0].direction is Direction.SUPPORT
