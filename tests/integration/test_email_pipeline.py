"""Integration tests for end-to-end Email OSINT pipeline execution."""

from __future__ import annotations

import pytest

from backend.email_osint import EmailOSINTEngine, EmailOSINTResult


@pytest.mark.asyncio
async def test_email_engine_end_to_end_mocked():
    engine = EmailOSINTEngine()
    result: EmailOSINTResult = await engine.discover("user@example.com")

    assert result.email == "user@example.com"
    assert result.normalized_email == "user@example.com"
    assert result.domain_intel.domain == "example.com"
    assert result.sources_checked >= 4
    assert isinstance(result.overall_confidence, float)
    assert len(result.identity_graph.nodes) >= 1
