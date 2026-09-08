"""Deterministic, fictional connector fixtures.

These records use an Osin-owned fixture format.  They do not claim to mirror
any current third-party CLI output and are never fetched from the network.
The reserved ``.invalid`` host is used for non-platform fixture URLs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

PRIMARY_GITHUB_URL = "https://github.com/alice_dev"
PRIMARY_REDDIT_URL = "https://www.reddit.com/user/alice_dev"
ALTERNATIVE_GITHUB_URL = "https://github.com/alice123"

PRIMARY_DOMAIN_URL = "https://alice.dev"
ALTERNATIVE_DOMAIN_URL = "https://alice123.invalid"


_PROFILE_RECORDS: dict[str, dict[str, Any]] = {
    "github_alice_dev": {
        "fixture_id": "github_alice_dev",
        "platform": "github",
        "platform_account_id": "github-fixture-1001",
        "username": "alice_dev",
        "display_name": "Alice Rivera",
        "canonical_url": PRIMARY_GITHUB_URL,
        "bio": "Open-source developer building privacy-friendly tools.",
        "location": "Berlin, Germany",
        "employer": "Open Civic Lab",
        "external_links": [PRIMARY_DOMAIN_URL, PRIMARY_REDDIT_URL],
        "avatar_url": "https://fixtures.invalid/avatars/alice-dev-github.png",
    },
    "reddit_alice_dev": {
        "fixture_id": "reddit_alice_dev",
        "platform": "reddit",
        "platform_account_id": "reddit-fixture-t2-1001",
        "username": "alice_dev",
        "display_name": "Alice Rivera",
        "canonical_url": PRIMARY_REDDIT_URL,
        "bio": "Open source, Python, and digital rights.",
        "location": "Berlin, Germany",
        "employer": None,
        "external_links": [PRIMARY_DOMAIN_URL, PRIMARY_GITHUB_URL],
        "avatar_url": "https://fixtures.invalid/avatars/alice-dev-reddit.png",
    },
    "github_alice123": {
        "fixture_id": "github_alice123",
        "platform": "github",
        "platform_account_id": "github-fixture-2002",
        "username": "alice123",
        "display_name": "Alice Chen",
        "canonical_url": ALTERNATIVE_GITHUB_URL,
        "bio": "Frontend engineer and street photographer.",
        "location": "Toronto, Canada",
        "employer": "Northstar Studio",
        "external_links": [ALTERNATIVE_DOMAIN_URL],
        "avatar_url": "https://fixtures.invalid/avatars/alice123-github.png",
    },
}


_DISCOVERY_FIXTURES: dict[str, dict[str, tuple[str, ...]]] = {
    "maigret": {
        "alice_dev": (
            "github_alice_dev",
            "reddit_alice_dev",
            "github_alice123",
        )
    },
    "sherlock": {
        "alice_dev": (
            "github_alice_dev",
            "reddit_alice_dev",
        )
    },
}


_SYLVA_FIXTURES: dict[str, dict[str, Any]] = {
    "alice_dev": {
        "identifiers": [
            {
                "type": "USERNAME",
                "value": "alice_dev",
                "normalized_value": "alice_dev",
                "profile_url": PRIMARY_GITHUB_URL,
                "source_url": PRIMARY_GITHUB_URL,
                "metadata": {"role": "expanded_alias"},
            },
            {
                "type": "DOMAIN",
                "value": "alice.dev",
                "normalized_value": "alice.dev",
                "profile_url": PRIMARY_GITHUB_URL,
                "source_url": PRIMARY_GITHUB_URL,
                "metadata": {"role": "public_personal_domain"},
            },
        ],
        "relationships": [
            {
                "source_type": "USERNAME",
                "source_value": "alice_dev",
                "relationship_type": "PUBLICLY_LINKS_TO",
                "target_type": "DOMAIN",
                "target_value": "alice.dev",
                "reliability": 0.9,
                "source_url": PRIMARY_GITHUB_URL,
            }
        ],
    },
    "alice123": {
        "identifiers": [
            {
                "type": "USERNAME",
                "value": "alice123",
                "normalized_value": "alice123",
                "profile_url": ALTERNATIVE_GITHUB_URL,
                "source_url": ALTERNATIVE_GITHUB_URL,
                "metadata": {"role": "expanded_alias"},
            },
            {
                "type": "DOMAIN",
                "value": "alice123.invalid",
                "normalized_value": "alice123.invalid",
                "profile_url": ALTERNATIVE_GITHUB_URL,
                "source_url": ALTERNATIVE_GITHUB_URL,
                "metadata": {"role": "public_personal_domain"},
            },
        ],
        "relationships": [
            {
                "source_type": "USERNAME",
                "source_value": "alice123",
                "relationship_type": "PUBLICLY_LINKS_TO",
                "target_type": "DOMAIN",
                "target_value": "alice123.invalid",
                "reliability": 0.9,
                "source_url": ALTERNATIVE_GITHUB_URL,
            }
        ],
    },
}


_SOCIAL_ANALYZER_FIXTURES: dict[str, dict[str, Any]] = {
    PRIMARY_GITHUB_URL: {
        "profile_id": "github_alice_dev",
        "observations": [
            {
                "signal_type": "public_external_link",
                "value": PRIMARY_DOMAIN_URL,
                "reliability": 0.9,
                "source_url": PRIMARY_GITHUB_URL,
            },
            {
                "signal_type": "public_display_name",
                "value": "Alice Rivera",
                "reliability": 0.8,
                "source_url": PRIMARY_GITHUB_URL,
            },
        ],
    },
    PRIMARY_REDDIT_URL: {
        "profile_id": "reddit_alice_dev",
        "observations": [
            {
                "signal_type": "public_external_link",
                "value": PRIMARY_DOMAIN_URL,
                "reliability": 0.9,
                "source_url": PRIMARY_REDDIT_URL,
            },
            {
                "signal_type": "public_display_name",
                "value": "Alice Rivera",
                "reliability": 0.75,
                "source_url": PRIMARY_REDDIT_URL,
            },
        ],
    },
    ALTERNATIVE_GITHUB_URL: {
        "profile_id": "github_alice123",
        "observations": [
            {
                "signal_type": "public_external_link",
                "value": ALTERNATIVE_DOMAIN_URL,
                "reliability": 0.9,
                "source_url": ALTERNATIVE_GITHUB_URL,
            },
            {
                "signal_type": "public_display_name",
                "value": "Alice Chen",
                "reliability": 0.8,
                "source_url": ALTERNATIVE_GITHUB_URL,
            },
        ],
    },
}


_GITFIVE_FIXTURES: dict[str, dict[str, Any]] = {
    PRIMARY_GITHUB_URL: {
        "observations": [
            {
                "signal_type": "github_public_name_history",
                "value": ["Alice Rivera"],
                "reliability": 0.85,
                "source_url": PRIMARY_GITHUB_URL,
            },
            {
                "signal_type": "github_public_repositories",
                "value": ["identity-graph", "public-profile-tools"],
                "reliability": 0.95,
                "source_url": PRIMARY_GITHUB_URL,
            },
            {
                "signal_type": "github_public_domain",
                "value": "alice.dev",
                "reliability": 0.95,
                "source_url": PRIMARY_GITHUB_URL,
            },
        ],
        "identifiers": [
            {
                "type": "USERNAME",
                "value": "alice_dev",
                "normalized_value": "alice_dev",
                "profile_url": PRIMARY_GITHUB_URL,
                "source_url": PRIMARY_GITHUB_URL,
                "metadata": {"role": "current_github_username"},
            },
            {
                "type": "REPOSITORY",
                "value": "identity-graph",
                "normalized_value": "identity-graph",
                "profile_url": PRIMARY_GITHUB_URL,
                "source_url": f"{PRIMARY_GITHUB_URL}/identity-graph",
                "metadata": {"visibility": "public"},
            },
        ],
    },
    ALTERNATIVE_GITHUB_URL: {
        "observations": [
            {
                "signal_type": "github_public_name_history",
                "value": ["Alice Chen"],
                "reliability": 0.85,
                "source_url": ALTERNATIVE_GITHUB_URL,
            },
            {
                "signal_type": "github_public_repositories",
                "value": ["photo-map"],
                "reliability": 0.95,
                "source_url": ALTERNATIVE_GITHUB_URL,
            },
            {
                "signal_type": "github_public_domain",
                "value": "alice123.invalid",
                "reliability": 0.95,
                "source_url": ALTERNATIVE_GITHUB_URL,
            },
        ],
        "identifiers": [
            {
                "type": "USERNAME",
                "value": "alice123",
                "normalized_value": "alice123",
                "profile_url": ALTERNATIVE_GITHUB_URL,
                "source_url": ALTERNATIVE_GITHUB_URL,
                "metadata": {"role": "current_github_username"},
            },
            {
                "type": "REPOSITORY",
                "value": "photo-map",
                "normalized_value": "photo-map",
                "profile_url": ALTERNATIVE_GITHUB_URL,
                "source_url": f"{ALTERNATIVE_GITHUB_URL}/photo-map",
                "metadata": {"visibility": "public"},
            },
        ],
    },
}


def discovery_fixture(connector: str, username: str) -> list[dict[str, Any]]:
    """Return fresh records so callers cannot mutate global fixtures."""

    keys = _DISCOVERY_FIXTURES.get(connector, {}).get(username.casefold(), ())
    return [deepcopy(_PROFILE_RECORDS[key]) for key in keys]


def profile_fixture(fixture_id: str) -> dict[str, Any] | None:
    record = _PROFILE_RECORDS.get(fixture_id)
    return deepcopy(record) if record is not None else None


def sylva_fixture(identifier: str) -> dict[str, Any] | None:
    record = _SYLVA_FIXTURES.get(identifier.casefold())
    return deepcopy(record) if record is not None else None


def social_analyzer_fixture(canonical_url: str) -> dict[str, Any] | None:
    record = _SOCIAL_ANALYZER_FIXTURES.get(canonical_url.rstrip("/"))
    return deepcopy(record) if record is not None else None


def gitfive_fixture(canonical_url: str) -> dict[str, Any] | None:
    record = _GITFIVE_FIXTURES.get(canonical_url.rstrip("/"))
    return deepcopy(record) if record is not None else None
