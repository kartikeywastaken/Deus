"""Pure parser/planner regression inputs, never runtime profile substitutes."""

from types import SimpleNamespace

import pytest

from backend.connectors import CandidateProfile, ConnectorResult, ConnectorRunStatus
from backend.connectors.profile_links import declared_profiles, profile_link
from backend.connectors.registry import build_default_registry
from backend.connectors.website import Links
from backend.core.enums import SeedType
from backend.investigation.account_groups import account_details
from backend.investigation.pivot_engine import PivotEngine


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/account",
        "https://linkedin.com/in/account",
        "https://facebook.com/account",
        "https://twitter.com/account",
        "https://tiktok.com/@account",
        "https://youtube.com/@account",
        "https://reddit.com/u/account",
    ],
)
def test_major_social_account_urls(url):
    assert profile_link(url)
    assert (
        PivotEngine(build_default_registry()).discovery(SeedType.PROFILE_URL, url)[0].connector_name
        == "website"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/person/repo",
        "https://instagram.com/p/post",
        "https://x.com/intent",
        "https://linkedin.com/company/company",
    ],
)
def test_posts_repos_and_navigation_are_not_accounts(url):
    assert profile_link(url) is None


def test_declarations_preserve_different_handle_without_claiming_existence():
    p = CandidateProfile(
        platform="github",
        username="seed",
        canonical_url="https://github.com/seed",
        external_links=["https://instagram.com/different"],
    )
    r = declared_profiles(
        ConnectorResult(
            connector="github",
            connector_version="test",
            status=ConnectorRunStatus.SUCCESS,
            profiles=[p],
        )
    )
    assert r.profiles[1].username == "different"
    assert r.profiles[1].raw["destination_existence"] == "UNVERIFIED"
    assert len(declared_profiles(r).profiles) == 2


def test_ordinary_anchors_do_not_assert_ownership():
    parser = Links()
    parser.feed(
        '<a href="https://github.com/dependency">dependency</a>'
        '<a rel="me noopener" href="https://instagram.com/account">me</a>'
    )
    assert parser.identity_links == ["https://instagram.com/account"]
    assert len(parser.links) == 2


def test_unlinked_candidates_stay_separate():
    profiles = [
        SimpleNamespace(id=i, canonical_url=url, external_links=links, bio=None)
        for i, url, links in [(1, "a", ["b"]), (2, "b", []), (3, "c", [])]
    ]
    details = account_details(profiles)
    assert details[1]["analysis_status"] == details[2]["analysis_status"] == "PUBLICLY_LINKED"
    assert details[3]["analysis_status"] == "POSSIBLE_MATCH_NO_CONTEXT"
