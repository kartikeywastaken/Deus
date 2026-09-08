from __future__ import annotations

from backend.connectors import CandidateProfile, build_default_registry
from backend.core.enums import SeedType
from backend.correlation import build_identity_hypotheses
from backend.investigation.pivot_engine import PivotEngine, PivotLedger
from backend.investigation.question_planner import (
    HypothesisSnapshot,
    plan_disambiguation_question,
)
from backend.investigation.stopping import StopReason, evaluate_stopping
from backend.investigation.target_ranking import rank_hypotheses_for_seed
from backend.normalization import normalize_profile


def test_pivot_engine_selects_ordered_connector_subset_and_prevents_loops() -> None:
    engine = PivotEngine(build_default_registry(mock_connectors=True))
    ledger = PivotLedger()

    discovery = engine.discovery(SeedType.USERNAME, "Alice_Dev")

    assert [pivot.connector_name for pivot in discovery] == ["maigret", "sherlock"]
    first_claim = engine.claim_within_limit(discovery, ledger, remaining_runs=1)
    second_claim = engine.claim_within_limit(discovery, ledger, remaining_runs=5)
    assert [pivot.connector_name for pivot in first_claim] == ["maigret"]
    assert [pivot.connector_name for pivot in second_claim] == ["sherlock"]


def test_pivot_engine_runs_gitfive_only_for_github() -> None:
    engine = PivotEngine(build_default_registry(mock_connectors=True))
    github = CandidateProfile(
        platform="github",
        username="alice_dev",
        canonical_url="https://github.com/alice_dev",
    )
    reddit = CandidateProfile(
        platform="reddit",
        username="alice_dev",
        canonical_url="https://reddit.com/u/alice_dev",
    )

    pivots = engine.enrichment([github, reddit])

    assert sum(pivot.connector_name == "social_analyzer" for pivot in pivots) == 2
    assert sum(pivot.connector_name == "gitfive" for pivot in pivots) == 1


def test_question_planner_selects_one_material_location_question() -> None:
    profiles = {
        "primary": normalize_profile(
            {
                "id": "primary",
                "platform": "github",
                "canonical_url": "https://github.com/alice_dev",
                "username": "alice_dev",
                "location": "Berlin, Germany",
            }
        ),
        "alternative": normalize_profile(
            {
                "id": "alternative",
                "platform": "github",
                "canonical_url": "https://github.com/alice123",
                "username": "alice123",
                "location": "Toronto, Canada",
            }
        ),
    }
    hypotheses = (
        HypothesisSnapshot("first", 0.62, "LIKELY", ("primary",)),
        HypothesisSnapshot("second", 0.36, "AMBIGUOUS", ("alternative",)),
    )

    question = plan_disambiguation_question(hypotheses, profiles)

    assert question is not None
    assert "location" in question.question_text
    assert len(question.options) == 4
    assert question.options[-1].value == "skip"


def test_question_planner_does_not_ask_when_leader_is_decisive() -> None:
    profile = normalize_profile(
        {
            "id": "profile",
            "platform": "github",
            "canonical_url": "https://github.com/alice_dev",
            "location": "Berlin",
        }
    )
    other = normalize_profile(
        {
            "id": "other",
            "platform": "github",
            "canonical_url": "https://github.com/other",
            "location": "Toronto",
        }
    )

    result = plan_disambiguation_question(
        (
            HypothesisSnapshot("first", 0.9, "STRONG", ("profile",)),
            HypothesisSnapshot("second", 0.1, "WEAK", ("other",)),
        ),
        {"profile": profile, "other": other},
    )

    assert result is None


def test_stopping_rules_enforce_limits_before_confidence() -> None:
    result = evaluate_stopping(
        elapsed_seconds=601,
        max_duration_seconds=600,
        pivot_depth=0,
        max_pivot_depth=3,
        connector_runs=1,
        max_connector_runs=30,
        pending_question=False,
        leading_score=0.9,
    )

    assert result.should_stop
    assert result.reason is StopReason.SEARCH_DURATION_LIMIT


def test_stopping_rules_continue_only_for_valuable_pivot() -> None:
    result = evaluate_stopping(
        elapsed_seconds=2,
        max_duration_seconds=600,
        pivot_depth=1,
        max_pivot_depth=3,
        connector_runs=5,
        max_connector_runs=30,
        pending_question=False,
        valuable_pivots_available=True,
    )

    assert not result.should_stop
    assert result.reason is StopReason.CONTINUE


def test_target_ranking_keeps_similar_singleton_as_visible_alternative() -> None:
    profiles = (
        normalize_profile(
            {
                "id": "primary",
                "platform": "github",
                "canonical_url": "https://github.com/alice_dev",
                "username": "alice_dev",
            }
        ),
        normalize_profile(
            {
                "id": "alternative",
                "platform": "github",
                "canonical_url": "https://github.com/alice123",
                "username": "alice123",
            }
        ),
    )
    hypotheses = build_identity_hypotheses(profiles, ())

    ranked = rank_hypotheses_for_seed(
        hypotheses,
        profiles,
        seed_type=SeedType.USERNAME,
        seed_value="alice_dev",
    )

    assert ranked[0].memberships[0].profile_id == "primary"
    assert ranked[1].classification.value == "LIKELY"
    assert ranked[0].overall_score - ranked[1].overall_score <= 0.40
