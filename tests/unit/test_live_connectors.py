"""Offline contract tests. These doubles are never used by application searches."""

from unittest.mock import AsyncMock

import httpx
import pytest

from backend.connectors import ConnectorInput, ConnectorInputType, build_default_registry, live_cli
from backend.connectors.github import GitHubConnector
from backend.core.config import Settings


def seed(value="test-user", kind=ConnectorInputType.USERNAME):
    return ConnectorInput(type=kind, value=value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (404, "NO_RESULTS"),
        (401, "AUTH_REQUIRED"),
        (403, "RATE_LIMITED"),
        (429, "RATE_LIMITED"),
        (500, "FAILED"),
    ],
)
async def test_github_failure_has_no_fabricated_profiles(code, status):
    connector = GitHubConnector(httpx.MockTransport(lambda request: httpx.Response(code)))
    result = await connector.discover(seed())
    assert result.status == status
    assert result.profiles == []
    assert result.request_count == 1


@pytest.mark.asyncio
async def test_github_preserves_public_links_and_provenance():
    def handler(request):
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer test-only-token"
        if request.url.path.endswith("/social_accounts"):
            return httpx.Response(
                200, json=[{"provider": "custom", "url": "https://dev.to/test-user"}]
            )
        return httpx.Response(
            200,
            json={
                "type": "User",
                "id": 123,
                "login": "test-user",
                "html_url": "https://github.com/test-user",
                "name": "Test User",
                "blog": "example.org",
            },
        )

    result = await GitHubConnector(httpx.MockTransport(handler), token="test-only-token").discover(
        seed()
    )
    assert result.status == "SUCCESS"
    assert result.profiles[0].platform_account_id == "123"
    assert result.profiles[0].external_links == ["https://example.org"]
    assert result.observations[0].value == "https://dev.to/test-user"
    assert "/social_accounts" in result.observations[0].source_url
    assert result.request_count == 2
    assert "test-only-token" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_github_keeps_profile_if_link_collection_fails():
    def handler(request):
        if request.url.path.endswith("/social_accounts"):
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "type": "User",
                "id": 123,
                "login": "test-user",
                "html_url": "https://github.com/test-user",
            },
        )

    result = await GitHubConnector(httpx.MockTransport(handler)).discover(seed())
    assert result.status == "PARTIAL"
    assert len(result.profiles) == 1
    assert "429" in result.message


@pytest.mark.asyncio
async def test_github_rejects_arbitrary_urls_without_network():
    def forbidden(request):
        raise AssertionError("Unexpected HTTP request")

    result = await GitHubConnector(httpx.MockTransport(forbidden)).discover(
        seed("http://127.0.0.1/private", ConnectorInputType.PROFILE_URL)
    )
    assert not result.has_results


@pytest.mark.asyncio
async def test_cli_only_claimed_rows_become_candidates(monkeypatch):
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"", b"")
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(live_cli.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(live_cli, "version", lambda _: "test-version")
    monkeypatch.setattr(live_cli.shutil, "which", lambda _: "/test/sherlock")
    monkeypatch.setattr(
        live_cli,
        "read_reports",
        lambda _: [
            {"name": "GitHub", "exists": "Claimed", "url_user": "https://github.com/test-user"},
            {
                "name": "Reddit",
                "exists": "Unknown",
                "url_user": "https://reddit.com/user/test-user",
            },
            {"name": "Dev.to", "exists": "Available", "url_user": "https://dev.to/test-user"},
        ],
    )
    result = await live_cli.discover_live("sherlock", "test-user")
    assert result.status == "PARTIAL"
    assert [profile.platform for profile in result.profiles] == ["github"]
    assert len(result.raw_records) == 3
    assert "--local" in spawn.call_args.args
    assert "shell" not in spawn.call_args.kwargs
    spawn.reset_mock()
    invalid = await live_cli.discover_live("sherlock", "--help")
    assert not invalid.has_results
    spawn.assert_not_called()


def test_default_runtime_is_live():
    assert Settings(_env_file=None).mock_connectors is False
    registry = build_default_registry()
    assert all(connector.mode == "LIVE" for connector in registry)
    assert "github" in registry.names
