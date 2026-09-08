from __future__ import annotations

from backend.normalization.profiles import deduplicate_profiles, normalize_profile


def test_profile_normalization_canonicalizes_nested_identity_fields() -> None:
    profile = normalize_profile(
        {
            "id": "p1",
            "platform": " GitHub ",
            "platform_account_id": "42",
            "username": "@Alice_Dev",
            "display_name": " Alice Dév ",
            "canonical_url": "github.com/Alice_Dev/",
            "external_links": [
                "https://www.alice.dev/?utm_source=github",
                "https://alice.dev",
            ],
            "employer": "Example Labs",
        }
    )

    assert profile.platform == "github"
    assert profile.normalized_username == "alice_dev"
    assert profile.compact_username == "alicedev"
    assert profile.normalized_display_name == "alice dev"
    assert profile.canonical_url == "https://github.com/alice_dev"
    assert profile.external_links == ("https://alice.dev",)
    assert profile.personal_domains == ("alice.dev",)
    assert profile.normalized_organization == "example labs"


def test_deduplication_merges_same_platform_url_and_preserves_provenance() -> None:
    first = normalize_profile(
        {
            "id": "first",
            "platform": "github",
            "username": "Alice",
            "canonical_url": "https://github.com/Alice",
            "source_observation_ids": ["obs-1"],
        }
    )
    second = normalize_profile(
        {
            "id": "second",
            "platform": "github",
            "display_name": "Alice Doe",
            "canonical_url": "github.com/alice/",
            "external_links": ["alice.dev"],
            "source_observation_ids": ["obs-2"],
        }
    )

    result = deduplicate_profiles((first, second))

    assert len(result) == 1
    assert result[0].profile_id == "first"
    assert result[0].display_name == "Alice Doe"
    assert result[0].external_links == ("https://alice.dev",)
    assert result[0].source_observation_ids == ("obs-1", "obs-2")


def test_deduplication_never_merges_same_username_across_platforms() -> None:
    github = normalize_profile(
        {
            "id": "github",
            "platform": "github",
            "username": "alice",
            "canonical_url": "github.com/alice",
        }
    )
    reddit = normalize_profile(
        {
            "id": "reddit",
            "platform": "reddit",
            "username": "alice",
            "canonical_url": "reddit.com/u/alice",
        }
    )

    assert deduplicate_profiles((github, reddit)) == (github, reddit)
