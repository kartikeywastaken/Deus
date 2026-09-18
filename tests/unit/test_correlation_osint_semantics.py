"""Comprehensive unit and regression tests for OSINT evidence semantics, provenance, clustering, and correlation integrity."""

from __future__ import annotations

import pytest
from uuid import uuid4

from backend.connectors.schemas import CandidateProfile
from backend.correlation.clustering import build_identity_hypotheses
from backend.correlation.features import (
    Classification,
    Direction,
    EvidenceFamily,
    EvidenceSignal,
    PairAssessment,
    SignalType,
)
from backend.correlation.scorer import CorrelationScorer, score_evidence
from backend.email_osint.schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus
from backend.extraction.usernames import extract_username_evidence
from backend.normalization.profiles import NormalizedProfile, normalize_profile
from backend.reports.builder import build_report
from backend.reports.schemas import ReportEvidence, ReportHypothesis, ReportProfile


def test_account_discovery_does_not_equal_identity_confirmation():
    """Verify that discovering an account is classified as candidate, not identity confirmation."""
    profile = normalize_profile({
        "id": "p1",
        "platform": "github",
        "username": "kartikey",
        "canonical_url": "https://github.com/kartikey",
    })
    hypotheses = build_identity_hypotheses([profile], [])
    assert len(hypotheses) == 1
    # A single profile without matching pairwise evidence is WEAK candidate hypothesis, not confirmed
    assert hypotheses[0].classification == Classification.WEAK
    assert hypotheses[0].overall_score == 0.0


def test_observed_identifier_distinct_from_derived_identifier():
    """Verify distinction in provenance and confidence between observed vs derived identifiers."""
    obs = DiscoveredIdentifier(
        type="username",
        value="kartikey_dev",
        normalized_value="kartikey_dev",
        source="github_email",
        confidence=0.98,
        metadata={"provenance": "OBSERVED"},
    )
    der = DiscoveredIdentifier(
        type="username",
        value="kartikey",
        normalized_value="kartikey",
        source="email_derivation",
        confidence=0.30,
        metadata={"provenance": "DERIVED"},
    )

    assert obs.metadata["provenance"] == "OBSERVED"
    assert obs.confidence > 0.90
    assert der.metadata["provenance"] == "DERIVED"
    assert der.confidence < 0.50


def test_evidence_family_prevents_double_counting():
    """Verify that multiple signals from the same EvidenceFamily select at most one signal."""
    scorer = CorrelationScorer()
    
    # Two signals from USERNAME_IDENTITY family
    exact_match = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.USERNAME_EXACT,
        direction=Direction.SUPPORT,
        normalized_score=0.9,
        reliability=0.9,
        evidence_family=EvidenceFamily.USERNAME_IDENTITY,
        explanation="Both profiles use the same username 'kartikey'.",
    )
    similarity_match = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.USERNAME_SIMILARITY,
        direction=Direction.SUPPORT,
        normalized_score=0.8,
        reliability=0.75,
        evidence_family=EvidenceFamily.USERNAME_IDENTITY,
        explanation="The usernames 'kartikey' and 'kartikey' are lexically similar.",
    )

    assessment = scorer.score([exact_match, similarity_match], left_profile_id="p1", right_profile_id="p2")

    # Only 1 signal selected from the USERNAME_IDENTITY family
    assert len(assessment.selected_evidence) == 1
    assert assessment.selected_evidence[0].signal_type == SignalType.USERNAME_EXACT
    assert assessment.support_family_count == 1


def test_contradictions_remain_visible():
    """Verify supporting and contradictory evidence are kept distinct and visible."""
    scorer = CorrelationScorer()
    
    support_signal = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.USERNAME_EXACT,
        direction=Direction.SUPPORT,
        normalized_score=0.9,
        reliability=0.9,
        evidence_family=EvidenceFamily.USERNAME_IDENTITY,
        explanation="Username match: 'kartikey' on both accounts.",
    )
    contradiction_signal = EvidenceSignal(
        left_profile_id="p1",
        right_profile_id="p2",
        signal_type=SignalType.LOCATION_CONFLICT,
        direction=Direction.CONTRADICT,
        normalized_score=1.0,
        reliability=0.9,
        evidence_family=EvidenceFamily.LOCATION_IDENTITY,
        explanation="Location conflict: 'San Francisco' vs 'London'.",
    )

    assessment = scorer.score([support_signal, contradiction_signal], left_profile_id="p1", right_profile_id="p2")

    assert len(assessment.selected_evidence) == 2
    assert assessment.support_family_count == 1
    assert assessment.contradiction_family_count == 1
    assert any(e.direction == Direction.CONTRADICT for e in assessment.selected_evidence)


def test_conservative_clustering_non_transitivity():
    """Verify that A<=>B and B<=>C does NOT merge into A<=>B<=>C when A<=>C is missing or contradictory."""
    pA = normalize_profile({"id": "A", "platform": "github", "canonical_url": "https://github.com/A"})
    pB = normalize_profile({"id": "B", "platform": "reddit", "canonical_url": "https://reddit.com/user/B"})
    pC = normalize_profile({"id": "C", "platform": "twitter", "canonical_url": "https://twitter.com/C"})

    # Strong assessment between A and B
    ass_AB = PairAssessment(
        left_profile_id="A",
        right_profile_id="B",
        raw_score=50.0,
        normalized_score=0.50,
        classification=Classification.STRONG,
        evidence=(),
        selected_evidence=(),
        contributions=(),
        support_family_count=2,
        contradiction_family_count=0,
        model_version="deterministic-v0.1",
    )
    # Strong assessment between B and C
    ass_BC = PairAssessment(
        left_profile_id="B",
        right_profile_id="C",
        raw_score=50.0,
        normalized_score=0.50,
        classification=Classification.STRONG,
        evidence=(),
        selected_evidence=(),
        contributions=(),
        support_family_count=2,
        contradiction_family_count=0,
        model_version="deterministic-v0.1",
    )
    # Missing assessment between A and C (or weak/contradictory)

    hypotheses = build_identity_hypotheses([pA, pB, pC], [ass_AB, ass_BC])

    # A and B merge into one hypothesis; C remains separate because A<=>C link is missing!
    assert len(hypotheses) == 2
    cluster_sizes = [len(h.profile_ids) for h in hypotheses]
    assert sorted(cluster_sizes) == [1, 2]


def test_report_builder_connector_summary_and_why_this_result():
    """Verify build_report constructs why_this_result and connector_summary correctly."""
    s_id = uuid4()
    p1 = ReportProfile(
        id=uuid4(),
        platform="github",
        username="kartikey",
        canonical_url="https://github.com/kartikey",
        score=0.8,
        classification="STRONG",
    )
    h1 = ReportHypothesis(
        id=uuid4(),
        rank=1,
        score=0.8,
        classification="STRONG",
        profiles=[p1],
    )
    e1 = ReportEvidence(
        signal_type="USERNAME_EXACT",
        direction="SUPPORT",
        explanation="Username match: 'kartikey' on github.com and reddit.com",
        normalized_score=0.9,
        reliability=0.9,
        source_urls=["https://github.com/kartikey"],
    )

    connector_runs = [
        {"connector": "github", "status": "SUCCESS"},
        {"connector": "maigret", "status": "NO_RESULTS"},
        {"connector": "linkedin", "status": "AUTH_REQUIRED", "error": "LinkedIn check requires operator opt-in"},
    ]

    report = build_report(
        search_run_id=s_id,
        hypotheses=[h1],
        evidence=[e1],
        connector_runs=connector_runs,
    )

    assert "why_this_result" in report.model_dump()
    assert report.why_this_result["evidence_strength"] == "STRONG"
    assert len(report.why_this_result["supporting_evidence"]) >= 1

    summary = report.connector_summary
    assert summary["sources_checked"] == 3
    assert "github" in summary["accounts_discovered"]
    assert "maigret" in summary["no_accounts_found"]
    assert len(summary["inconclusive_or_blocked"]) == 1
    assert summary["inconclusive_or_blocked"][0]["connector"] == "linkedin"
