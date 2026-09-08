from __future__ import annotations

from backend.correlation import Classification, correlate_profiles
from backend.normalization import normalize_profile


def test_correlation_facade_returns_primary_cluster_and_unmerged_alternative() -> None:
    github = normalize_profile(
        {
            "id": "github-alice",
            "platform": "github",
            "username": "alice_dev",
            "display_name": "Alice Rivera",
            "canonical_url": "https://github.com/alice_dev",
            "location": "Berlin, Germany",
            "external_links": [
                "https://alice.dev",
                "https://reddit.com/u/alice_dev",
            ],
        }
    )
    reddit = normalize_profile(
        {
            "id": "reddit-alice",
            "platform": "reddit",
            "username": "alice_dev",
            "display_name": "Alice Rivera",
            "canonical_url": "https://reddit.com/u/alice_dev",
            "location": "Berlin, Germany",
            "external_links": [
                "https://alice.dev",
                "https://github.com/alice_dev",
            ],
        }
    )
    alternative = normalize_profile(
        {
            "id": "github-alternative",
            "platform": "github",
            "username": "alice123",
            "display_name": "Alice Chen",
            "canonical_url": "https://github.com/alice123",
            "location": "Toronto, Canada",
            "external_links": ["https://alice123.invalid"],
        }
    )

    result = correlate_profiles((github, reddit, alternative))

    assert len(result.assessments) == 1
    assert result.assessments[0].classification is Classification.STRONG
    assert result.hypotheses[0].profile_ids == ("github-alice", "reddit-alice")
    assert result.hypotheses[1].profile_ids == ("github-alternative",)
