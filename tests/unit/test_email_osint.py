"""Unit tests for High-Performance Email OSINT & Identity Discovery Engine."""

from __future__ import annotations

import pytest

from backend.email_osint import (
    DiscoveredIdentifier,
    EmailDomainIntel,
    EmailOSINTEngine,
    EmailSourceResult,
    EmailSourceStatus,
)
from backend.email_osint.adapters.domain_intel import DomainIntelAdapter
from backend.email_osint.cache import EmailOSINTCache
from backend.email_osint.correlation import EmailCorrelationEngine
from backend.email_osint.graph import IdentityGraphBuilder
from backend.email_osint.resilience import CircuitBreaker


@pytest.mark.asyncio
async def test_domain_intel_adapter_gmail():
    adapter = DomainIntelAdapter()
    result = await adapter.check("testuser@gmail.com")

    assert result.status == EmailSourceStatus.FOUND
    assert result.account_exists is True
    assert result.confidence == 0.99
    assert len(result.identifiers) >= 1
    assert result.identifiers[0].value == "gmail.com"


@pytest.mark.asyncio
async def test_domain_intel_adapter_custom():
    adapter = DomainIntelAdapter()
    result = await adapter.check("alex@company.com")

    assert result.status == EmailSourceStatus.FOUND
    assert result.evidence.get("domain") == "company.com"


def test_circuit_breaker():
    cb = CircuitBreaker("test_source", max_failures=2, reset_timeout_seconds=60)
    assert cb.check_allowed() is True

    cb.record_failure()
    assert cb.check_allowed() is True

    cb.record_failure()
    assert cb.is_open is True
    assert cb.check_allowed() is False

    cb.record_success()
    assert cb.is_open is False
    assert cb.check_allowed() is True


def test_cache():
    cache = EmailOSINTCache(default_ttl_seconds=1.0)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    cache.clear()
    assert cache.get("key1") is None


def test_correlation_engine():
    identifiers = [
        DiscoveredIdentifier(type="username", value="user1", normalized_value="user1", source="s1"),
        DiscoveredIdentifier(type="username", value="user1", normalized_value="user1", source="s2"),
        DiscoveredIdentifier(type="domain", value="example.com", normalized_value="example.com", source="s1"),
    ]
    deduped = EmailCorrelationEngine.deduplicate_identifiers(identifiers)
    assert len(deduped) == 2

    source_results = [
        EmailSourceResult(
            source_name="s1",
            category="social",
            status=EmailSourceStatus.FOUND,
            account_exists=True,
            confidence=0.9,
            username="user1",
        ),
        EmailSourceResult(
            source_name="s2",
            category="developer",
            status=EmailSourceStatus.FOUND,
            account_exists=True,
            confidence=0.85,
            username="user1",
        ),
    ]
    conf = EmailCorrelationEngine.calculate_overall_confidence(source_results, deduped)
    assert conf >= 0.90


def test_identity_graph_builder():
    builder = IdentityGraphBuilder("target@example.com")
    builder.add_domain_intel("example.com", "Custom Corporate", org_hint="Example")
    builder.add_source_result(
        EmailSourceResult(
            source_name="github",
            category="developer",
            status=EmailSourceStatus.FOUND,
            account_exists=True,
            username="target_dev",
            canonical_url="https://github.com/target_dev",
            confidence=0.95,
        )
    )

    graph = builder.build()
    assert len(graph.nodes) >= 3
    assert len(graph.edges) >= 2
    assert any(n.label == "target@example.com" for n in graph.nodes)
