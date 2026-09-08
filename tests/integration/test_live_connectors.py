"""Actual external collection. No response replay and no manufactured profile data."""

import os

import pytest

from backend.connectors import ConnectorInput, ConnectorInputType, build_default_registry

pytestmark = pytest.mark.live


@pytest.mark.parametrize("name", ["github", "github_search", "maigret", "sherlock"])
async def test_live_username_connector(name):
    seed = os.getenv("DEUS_TEST_USERNAME")
    if not seed:
        pytest.skip("Set DEUS_TEST_USERNAME to an operator-controlled public username")
    result = (
        await build_default_registry()
        .get(name)
        .discover(ConnectorInput(type=ConnectorInputType.USERNAME, value=seed))
    )
    if result.status in {"UNAVAILABLE", "AUTH_REQUIRED", "RATE_LIMITED", "DISABLED", "MANUAL"}:
        pytest.skip(f"{name}: {result.status}: {result.message}")
    assert result.status in {"SUCCESS", "PARTIAL", "NO_RESULTS"}, result.message
    assert result.request_count > 0
    for profile in result.profiles:
        assert profile.source_url
        assert profile.raw
        assert profile.canonical_url.startswith("https://")
