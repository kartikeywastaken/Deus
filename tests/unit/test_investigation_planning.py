"""Pure planning examples are not external profile evidence."""

import pytest

from backend.connectors import build_default_registry
from backend.core.enums import SeedType
from backend.investigation.pivot_engine import PivotEngine, PivotLedger
from backend.investigation.planner import Action, choose_action
from backend.investigation.username_questions import question_spec, variants_from_answer


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
