"""Unit tests for Username OSINT & Identity Discovery Engine and API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.username_osint import (
    UsernameOSINTEngine,
    UsernameOSINTResult,
    UsernameSourceStatus,
)

client = TestClient(app)


@pytest.mark.asyncio
async def test_username_engine_discovery():
    engine = UsernameOSINTEngine()
    result = await engine.discover("testuser")

    assert isinstance(result, UsernameOSINTResult)
    assert result.username == "testuser"
    assert result.normalized_username == "testuser"
    assert result.sources_checked >= 1
    assert result.overall_confidence > 0.0


def test_username_api_endpoint():
    response = client.post("/api/osint/username", json={"username": "johndoe"})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "johndoe"
    assert data["normalized_username"] == "johndoe"
    assert "source_results" in data
    assert "sources_checked" in data


def test_username_api_validation():
    response = client.post("/api/osint/username", json={"username": "   "})
    assert response.status_code == 422
