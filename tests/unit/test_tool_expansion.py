"""Pure contract and boundary tests, not runtime simulated collection."""

import pytest

from backend.connectors.discovery_sites import check_details, site_database
from backend.connectors.osintgram_public import public_fields
from backend.connectors.profile_links import profile_link


def test_discovery_resolves_actual_tool_names():
    raw, names, missing = site_database("maigret")
    if not names:
        pytest.skip("maigret site database is not installed in this environment")
    for tool in ("maigret", "sherlock"):
        _, names, missing = site_database(tool)
        assert "DEV Community" in names
        assert "mastodon.social" in names
        assert "Bluesky" in names
        assert not set(names) & {"ImgInn", "Pixwox", "Steamidfinder"}
        assert "Dev.to" not in missing


def test_maigret_reasons_are_not_all_failures():
    rows = [
        {"name": "example", "exists": "Unknown", "http_status": code, "error_reason": reason}
        for code, reason in [
            (403, "Captcha error"),
            (429, "Rate limited"),
            (0, "Request timeout"),
            (401, ""),
        ]
    ]
    assert [x["status"] for x in check_details(rows)] == [
        "BLOCKED",
        "RATE_LIMITED",
        "TIMEOUT",
        "ACCESS_RESTRICTED",
    ]


def test_osintgram_discards_private_and_unknown_visibility():
    for flag in (True, None):
        result = public_fields(
            {"username": "example", "is_private": flag, "biography": "must not be returned"},
            "example",
        )
        assert result["status"] == "PARTIAL"
        assert "user" not in result


def test_osintgram_output_excludes_contacts_and_followers():
    result = public_fields(
        {
            "username": "example",
            "is_private": False,
            "public_email": "not-exported",
            "contact_phone_number": "not-exported",
            "followers": ["not-exported"],
            "external_url": "https://example.org",
            "bio_links": [{"url": "https://example.org", "extra": "not-exported"}],
        },
        "example",
    )
    assert "not-exported" not in str(result)
    assert result["user"]["bio_links"] == [{"url": "https://example.org"}]
    with pytest.raises(ValueError):
        public_fields({"username": "different", "is_private": False}, "example")


@pytest.mark.parametrize(
    "url",
    [
        "https://bsky.app/profile/example.bsky.social",
        "https://threads.com/@example",
        "https://linktr.ee/example",
        "https://codepen.io/example",
    ],
)
def test_additional_public_platform_links(url):
    assert profile_link(url)


def test_instagram_seed_can_use_osintgram_without_html_discovery():
    from backend.connectors.registry import build_default_registry
    from backend.core.enums import SeedType
    from backend.investigation.pivot_engine import PivotEngine

    pivots = PivotEngine(build_default_registry()).discovery(
        SeedType.PROFILE_URL, "https://instagram.com/example"
    )
    assert {p.connector_name for p in pivots} == {"website", "osintgram"}
