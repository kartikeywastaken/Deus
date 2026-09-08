from __future__ import annotations

import asyncio

import pytest

from backend.connectors import (
    CandidateProfile,
    Connector,
    ConnectorAvailability,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorRegistry,
    ConnectorRunStatus,
    DuplicateConnectorError,
    GitFiveConnector,
    MaigretConnector,
    SherlockConnector,
    SocialAnalyzerConnector,
    SylvaConnector,
    UnknownConnectorError,
    build_default_registry,
)
from backend.connectors.fixtures import (
    ALTERNATIVE_DOMAIN_URL,
    ALTERNATIVE_GITHUB_URL,
    PRIMARY_DOMAIN_URL,
    PRIMARY_GITHUB_URL,
    PRIMARY_REDDIT_URL,
)


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def username_seed(value: str = "alice_dev") -> ConnectorInput:
    return ConnectorInput(type=ConnectorInputType.USERNAME, value=value)


def test_connectors_satisfy_runtime_protocol() -> None:
    assert isinstance(MaigretConnector(), Connector)
    assert isinstance(SherlockConnector(), Connector)
    assert isinstance(SylvaConnector(), Connector)
    assert isinstance(SocialAnalyzerConnector(), Connector)
    assert isinstance(GitFiveConnector(), Connector)
    assert ConnectorInputType.USERNAME in MaigretConnector().accepts


def test_maigret_discovers_primary_pair_and_different_domain_alternative() -> None:
    result = run(MaigretConnector().discover(username_seed()))

    assert result.status is ConnectorRunStatus.SUCCESS
    assert result.request_count == 0
    assert {profile.canonical_url for profile in result.profiles} == {
        PRIMARY_GITHUB_URL,
        PRIMARY_REDDIT_URL,
        ALTERNATIVE_GITHUB_URL,
    }

    by_url = {profile.canonical_url: profile for profile in result.profiles}
    assert PRIMARY_DOMAIN_URL in by_url[PRIMARY_GITHUB_URL].external_links
    assert PRIMARY_DOMAIN_URL in by_url[PRIMARY_REDDIT_URL].external_links
    assert ALTERNATIVE_DOMAIN_URL in by_url[ALTERNATIVE_GITHUB_URL].external_links
    assert PRIMARY_DOMAIN_URL not in by_url[ALTERNATIVE_GITHUB_URL].external_links
    assert all(
        observation.signal_type == "public_profile_exists"
        for observation in result.observations
    )


def test_sherlock_overlaps_discovery_without_claiming_identity() -> None:
    maigret = run(MaigretConnector().discover(username_seed()))
    sherlock = run(SherlockConnector().discover(username_seed()))

    assert {profile.canonical_url for profile in sherlock.profiles} == {
        PRIMARY_GITHUB_URL,
        PRIMARY_REDDIT_URL,
    }
    assert {profile.canonical_url for profile in sherlock.profiles}.issubset(
        {profile.canonical_url for profile in maigret.profiles}
    )
    assert all(
        observation.raw_data["meaning"] == "candidate profile existence only"
        for observation in sherlock.observations
    )


def test_mock_results_are_deterministic_and_do_not_leak_mutation() -> None:
    connector = MaigretConnector()
    first = run(connector.discover(username_seed()))
    first.profiles[0].external_links.append("https://mutation.invalid")
    second = run(connector.discover(username_seed()))

    assert "https://mutation.invalid" not in second.profiles[0].external_links
    first.profiles[0].external_links.pop()
    assert first.model_dump() == second.model_dump()


def test_unknown_mock_seed_returns_no_results_instead_of_fabrication() -> None:
    result = run(MaigretConnector().discover(username_seed("not_a_fixture")))
    assert result.status is ConnectorRunStatus.NO_RESULTS
    assert result.profiles == []
    assert result.raw_records == []


def test_sylva_expands_known_alias_into_domain_relationship() -> None:
    result = run(SylvaConnector().discover(username_seed()))

    assert result.status is ConnectorRunStatus.SUCCESS
    identifiers = {
        (identifier.type.value, identifier.normalized_value)
        for identifier in result.identifiers
    }
    assert identifiers == {
        ("USERNAME", "alice_dev"),
        ("DOMAIN", "alice.dev"),
    }
    assert len(result.relationships) == 1
    assert result.relationships[0].relationship_type == "PUBLICLY_LINKS_TO"
    assert result.relationships[0].target_value == "alice.dev"


def test_social_analyzer_enriches_each_candidate_with_public_observations() -> None:
    discovered = run(MaigretConnector().discover(username_seed()))
    connector = SocialAnalyzerConnector()

    results = [run(connector.enrich(candidate)) for candidate in discovered.profiles]

    assert all(result.status is ConnectorRunStatus.SUCCESS for result in results)
    assert all(result.profiles for result in results)
    assert [result.profiles[0].canonical_url for result in results] == [
        profile.canonical_url for profile in discovered.profiles
    ]
    primary_values = {
        observation.value
        for result in results[:2]
        for observation in result.observations
        if observation.signal_type == "public_external_link"
    }
    assert primary_values == {PRIMARY_DOMAIN_URL}


def test_gitfive_enriches_only_known_github_candidates() -> None:
    discovered = run(MaigretConnector().discover(username_seed()))
    github = next(
        profile for profile in discovered.profiles if profile.canonical_url == PRIMARY_GITHUB_URL
    )
    reddit = next(
        profile for profile in discovered.profiles if profile.canonical_url == PRIMARY_REDDIT_URL
    )
    connector = GitFiveConnector()

    github_result = run(connector.enrich(github))
    reddit_result = run(connector.enrich(reddit))

    assert github_result.status is ConnectorRunStatus.SUCCESS
    assert {item.signal_type for item in github_result.observations} == {
        "github_public_name_history",
        "github_public_repositories",
        "github_public_domain",
    }
    assert any(item.normalized_value == "identity-graph" for item in github_result.identifiers)
    assert reddit_result.status is ConnectorRunStatus.NO_RESULTS


def test_gitfive_typed_discovery_requires_profile_context() -> None:
    connector = GitFiveConnector()
    no_context = ConnectorInput(
        type=ConnectorInputType.GITHUB_PROFILE,
        value=PRIMARY_GITHUB_URL,
    )
    result = run(connector.discover(no_context))
    assert result.status is ConnectorRunStatus.NO_RESULTS
    assert "requires" in (result.message or "").casefold()


def test_registry_selects_connectors_by_declared_capability() -> None:
    registry = build_default_registry(mock_connectors=True)

    assert registry.names == (
        "maigret",
        "sherlock",
        "sylva",
        "social_analyzer",
        "gitfive",
    )
    assert {connector.name for connector in registry.eligible_for(ConnectorInputType.USERNAME)} == {
        "maigret",
        "sherlock",
        "sylva",
    }
    assert {
        connector.name
        for connector in registry.eligible_for(
            ConnectorInputType.GITHUB_PROFILE, enrichment_only=True
        )
    } == {"gitfive"}


def test_registry_rejects_duplicate_and_unknown_names() -> None:
    registry = ConnectorRegistry([MaigretConnector()])
    with pytest.raises(DuplicateConnectorError):
        registry.register(MaigretConnector())
    with pytest.raises(UnknownConnectorError):
        registry.get("missing")


@pytest.mark.parametrize(
    ("connector", "expected_status", "expected_availability"),
    [
        (
            SylvaConnector(ConnectorMode.LIVE),
            ConnectorRunStatus.UNAVAILABLE,
            ConnectorAvailability.UNAVAILABLE,
        ),
        (
            GitFiveConnector(ConnectorMode.LIVE),
            ConnectorRunStatus.UNAVAILABLE,
            ConnectorAvailability.UNAVAILABLE,
        ),
    ],
)
def test_live_connectors_are_explicit_non_executing_placeholders(
    connector: Connector,
    expected_status: ConnectorRunStatus,
    expected_availability: ConnectorAvailability,
) -> None:
    result = run(connector.discover(username_seed()))
    assert result.status is expected_status
    assert connector.availability is expected_availability
    assert result.request_count == 0
    assert not result.has_results


def test_candidate_profile_rejects_blank_canonical_url() -> None:
    with pytest.raises(ValueError):
        CandidateProfile(platform="github", canonical_url="   ")
