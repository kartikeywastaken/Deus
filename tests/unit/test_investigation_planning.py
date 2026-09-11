"""Pure planning examples are not external profile evidence."""

import pytest

from backend.connectors import build_default_registry
from backend.core.enums import SeedType
from backend.investigation.pivot_engine import PivotEngine, PivotLedger
from backend.investigation.planner import Action, choose_action
from backend.investigation.orchestrator import _email_identifier_candidates
from backend.investigation.username_questions import question_spec, variants_from_answer
from backend.email_osint import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


def test_number_hint_generates_bounded_variants():
    assert set(variants_from_answer("username_digits", "handle", "123")) == {
        "handle123",
        "123handle",
    }
    assert variants_from_answer("username_digits", "handle", "skip") == ()
    for value in ("123456789", "../file", "１２", ""):
        with pytest.raises(ValueError):
            variants_from_answer("username_digits", "handle", value)


def test_live_discovery_and_durable_fingerprints():
    pivots = PivotEngine(build_default_registry()).discovery(SeedType.USERNAME, "handle")
    assert [p.connector_name for p in pivots] == ["github", "github_search", "maigret", "sherlock"]
    ledger = PivotLedger()
    assert ledger.claim(pivots[0])
    assert not ledger.claim(pivots[0])


def test_discover_before_question_and_stop_at_budget():
    args = dict(
        initial=("work",),
        hints=(),
        question=question_spec("username_numbers", "handle"),
        enrichment=(),
        runs_remaining=1,
        questions_remaining=2,
        pivot_remaining=2,
        leading_score=0,
    )
    assert choose_action(**args).kind == Action.RUN_CONNECTOR
    args["initial"] = ()
    assert choose_action(**args).kind == Action.ASK_QUESTION
    args["runs_remaining"] = 0
    assert choose_action(**args).kind == Action.STOP_INSUFFICIENT


def test_email_identifier_profile_urls_become_candidates():
    result = EmailSourceResult(
        source_name="holehe_public",
        category="enumeration",
        status=EmailSourceStatus.FOUND,
        account_exists=True,
        identifiers=[
            DiscoveredIdentifier(
                type="profile_url",
                value="https://duolingo.com/profile/alice",
                normalized_value="https://duolingo.com/profile/alice",
                source="holehe_public:duolingo",
                confidence=0.9,
                metadata={"platform": "duolingo"},
            )
        ],
        evidence={"found_services": ["duolingo"]},
    )

    candidates = _email_identifier_candidates(result)

    assert len(candidates) == 1
    assert candidates[0].platform == "duolingo"
    assert candidates[0].canonical_url == "https://duolingo.com/profile/alice"
