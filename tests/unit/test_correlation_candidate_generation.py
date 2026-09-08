from __future__ import annotations

from backend.correlation.candidate_generation import generate_candidate_pairs
from backend.correlation.features import BlockingReason
from backend.normalization.profiles import normalize_profile


def _profile(profile_id: str, platform: str, username: str, **extra):
    return normalize_profile(
        {
            "id": profile_id,
            "platform": platform,
            "username": username,
            "canonical_url": f"https://{platform}.example/{username}",
            **extra,
        }
    )


def test_blocking_returns_only_profiles_with_a_blocking_signal() -> None:
    github = _profile(
        "g",
        "github",
        "alice_dev",
        display_name="Alice Doe",
        external_links=["https://alice.dev", "https://reddit.example/alice-dev"],
    )
    reddit = _profile(
        "r",
        "reddit",
        "alice-dev",
        display_name="Alice Doe",
        external_links=["https://alice.dev"],
    )
    unrelated = _profile("x", "github", "totally_else", display_name="Bob Smith")

    pairs = generate_candidate_pairs((github, reddit, unrelated))

    assert [pair.pair_key for pair in pairs] == [("g", "r")]
    assert BlockingReason.EXACT_USERNAME in pairs[0].reasons
    assert BlockingReason.SHARED_DOMAIN in pairs[0].reasons
    assert BlockingReason.DIRECT_CROSS_LINK in pairs[0].reasons


def test_pgvector_neighbor_results_can_create_a_candidate_block() -> None:
    left = _profile("left", "github", "alpha")
    right = _profile("right", "reddit", "zulu")

    pairs = generate_candidate_pairs(
        (left, right), semantic_neighbors=[("left", "right")]
    )

    assert len(pairs) == 1
    assert pairs[0].reasons == (BlockingReason.SEMANTIC_NEIGHBOR,)


def test_unknown_neighbor_ids_are_ignored() -> None:
    profile = _profile("left", "github", "alpha")
    assert generate_candidate_pairs(
        (profile,), semantic_neighbors=[("left", "missing")]
    ) == ()
