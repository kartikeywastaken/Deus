"""Comprehensive unit tests for first-class identifier OSINT rework, correlation, source independence, and graph removal."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.correlation.features import Direction, EvidenceFamily, EvidenceSignal, SignalType
from backend.correlation.scorer import CorrelationScorer, score_evidence
from backend.extraction.identifiers import extract_identifier_evidence
from backend.normalization.profiles import NormalizedProfile, normalize_profile
from backend.reports.builder import build_report
from backend.reports.schemas import ReportEvidence, ReportHypothesis, ReportProfile


def test_email_seed_preservation():
    """Verify that email seed is preserved as an EMAIL identifier without auto-mutation to username."""
    email_seed = "investigate@target-domain.org"
    profile = normalize_profile({
        "id": "p1",
        "platform": "gravatar",
        "canonical_url": "https://gravatar.com/investigate",
        "emails": [email_seed],
    })
    assert email_seed in profile.emails
    assert profile.platform == "gravatar"


def test_username_seed_preservation():
    """Verify that username seed is preserved as a USERNAME identifier without auto-mutation to email."""
    username_seed = "target_analyst_2026"
    profile = normalize_profile({
        "id": "p2",
        "platform": "github",
        "username": username_seed,
        "canonical_url": f"https://github.com/{username_seed}",
    })
    assert profile.username == username_seed
    assert profile.normalized_username == username_seed


def test_exact_email_correlation_creates_explicit_signal():
    """Verify that exact email match creates explicit EMAIL_EXACT evidence signal."""
    email = "shared_contact@security-research.io"
    p1 = normalize_profile({
        "id": "p1",
        "platform": "github",
        "canonical_url": "https://github.com/user_a",
        "emails": [email],
    })
    p2 = normalize_profile({
        "id": "p2",
        "platform": "gitlab",
        "canonical_url": "https://gitlab.com/user_b",
        "emails": [email],
    })

    signals = extract_identifier_evidence(p1, p2)
    assert len(signals) >= 1
    email_signal = next(s for s in signals if s.signal_type == SignalType.EMAIL_EXACT)
    assert email_signal.direction == Direction.SUPPORT
    assert email_signal.normalized_score >= 0.90
    assert email_signal.evidence_family == EvidenceFamily.IDENTIFIER_IDENTITY
    assert email in email_signal.explanation


def test_exact_username_correlation_creates_explicit_signal():
    """Verify exact username match generates explicit USERNAME_EXACT evidence signal."""
    p1 = normalize_profile({
        "id": "p1",
        "platform": "github",
        "username": "unique_handle_x",
        "canonical_url": "https://github.com/unique_handle_x",
    })
    p2 = normalize_profile({
        "id": "p2",
        "platform": "dockerhub",
        "username": "unique_handle_x",
        "canonical_url": "https://hub.docker.com/u/unique_handle_x",
    })

    from backend.extraction.usernames import extract_username_evidence
    signals = extract_username_evidence(p1, p2)
    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.USERNAME_EXACT
    assert signals[0].normalized_score > 0.50


def test_source_independence_tracking():
    """Verify repeated observations from independent sources vs single source are tracked."""
    scorer = CorrelationScorer()

    s1 = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.EMAIL_EXACT,
        direction=Direction.SUPPORT,
        normalized_score=0.95,
        reliability=0.95,
        evidence_family=EvidenceFamily.IDENTIFIER_IDENTITY,
        explanation="Shared email on source A",
        source_key="source_github",
        metadata={"identifier_value": "user@domain.com"},
    )
    s2 = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.DOMAIN_EXACT,
        direction=Direction.SUPPORT,
        normalized_score=0.88,
        reliability=0.90,
        evidence_family=EvidenceFamily.WEB_IDENTITY,
        explanation="Shared domain on source B",
        source_key="source_keybase",
        metadata={"identifier_value": "domain.com"},
    )

    assessment = scorer.score([s1, s2], left_profile_id="p1", right_profile_id="p2")
    assert assessment.independent_source_count == 2
    assert "user@domain.com" in assessment.matching_identifiers
    assert "domain.com" in assessment.matching_identifiers


def test_timestamp_preservation_on_claims():
    """Verify temporal claims preserve validity intervals."""
    from backend.normalization.profiles import TemporalClaim
    from datetime import UTC, datetime

    start_dt = datetime(2025, 1, 1, tzinfo=UTC)
    end_dt = datetime(2026, 1, 1, tzinfo=UTC)
    claim = TemporalClaim(value="ACME Corp", normalized_value="acme corp", start=start_dt, end=end_dt)

    assert claim.start == start_dt
    assert claim.end == end_dt
    assert claim.value == "ACME Corp"


@pytest.mark.asyncio
async def test_no_graph_endpoint(monkeypatch):
    """Verify graph API endpoint has been completely removed."""
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/api/searches/{uuid4()}/graph")
    assert response.status_code == 404
