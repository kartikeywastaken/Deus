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
from backend.email_osint.adapters.holehe_public import (
    PinterestChecker,
    PUBLIC_CHECKERS,
    RedditChecker,
    TwitterChecker,
)
from backend.email_osint.adapters.domain_intel import DomainIntelAdapter
from backend.email_osint.cache import EmailOSINTCache
from backend.email_osint.correlation import EmailCorrelationEngine
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

def test_service_checkers_cover_named_sites():
    names = {checker.name for checker in PUBLIC_CHECKERS}
    for expected in {
        "spotify",
        "duolingo",
        "reddit",
        "linkedin",
        "instagram",
        "pinterest",
        "twitter",
        "microsoft",
        "tiktok",
        "snapchat",
        "amazon",
        "wordpress",
        "firefox",
    }:
        assert expected in names, f"missing site checker: {expected}"
    labels = {
        checker.name: (getattr(checker, "label", "") or checker.name.replace("_", " ").title())
        for checker in PUBLIC_CHECKERS
    }
    assert all(labels.values())


def test_request_checkers_interpret_availability():
    assert RedditChecker().interpret(200, "", {"available": False}) is True
    assert RedditChecker().interpret(200, "", {"available": True}) is False
    assert RedditChecker().interpret(200, "", {"unexpected": "shape"}) is None

    assert PinterestChecker().interpret(
        200, "", {"resource_response": {"data": {"id": "1"}}}
    ) is True
    assert PinterestChecker().interpret(200, "", {"resource_response": {"data": None}}) is False
    assert PinterestChecker().interpret(500, "", None) is None

    assert TwitterChecker().interpret(200, "", {"valid": False}) is True
    assert TwitterChecker().interpret(200, "", {"valid": True}) is False
    assert TwitterChecker().interpret(200, "", "not-json") is None


@pytest.mark.asyncio
async def test_holehe_adapter_records_every_site_status(monkeypatch):
    from backend.email_osint.adapters import holehe_public as module

    async def found(email, client):
        return {
            "exists": True,
            "confidence": 0.9,
            "canonical_url": "https://spotify.com",
            "display_name": "Spotify Account",
        }

    async def absent(email, client):
        return {"exists": False}

    async def unknown(email, client):
        return {"exists": None}

    for index, checker in enumerate(module.PUBLIC_CHECKERS):
        handler = found if index == 0 else absent if index == 1 else unknown
        monkeypatch.setattr(checker, "check", handler, raising=False)

    result = await module.HolehePublicAdapter().check("target@example.com")

    assert result.status == EmailSourceStatus.FOUND
    assert result.evidence["found_services"] == [module.PUBLIC_CHECKERS[0].name]

    status = result.evidence["site_status"]
    assert len(status) == len(module.PUBLIC_CHECKERS)
    assert status[module.PUBLIC_CHECKERS[0].name]["exists"] is True
    assert status[module.PUBLIC_CHECKERS[1].name]["exists"] is False
    assert status[module.PUBLIC_CHECKERS[2].name]["exists"] is None
    assert all(entry["label"] for entry in status.values())
