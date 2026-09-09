"""Pure regression tests. Literal inputs are not simulated runtime collection."""

import sys

import pytest

from backend.connectors.gitfive import parse_light
from backend.connectors.process import run_process
from backend.connectors.social_live import same_profile, site_for_url
from backend.correlation.engine import candidate_relevance
from backend.investigation.question_planner import HypothesisSnapshot, plan_disambiguation_question
from backend.normalization import normalize_profile


def test_seed_bonus_does_not_change_identity_score():
    result = candidate_relevance("Handle", "handle")
    assert result["score"] == 0.15
    assert result["identity_score"] == 0
    assert candidate_relevance("other", "handle")["score"] == 0
    assert candidate_relevance("handle", "handle", seed_type="NAME")["score"] == 0


def test_social_analyzer_does_not_confirm_different_account_on_same_host():
    assert same_profile("https://github.com/handle/", "https://github.com/handle")
    assert not same_profile("https://github.com/someone-else", "https://github.com/handle")
    assert site_for_url("https://127.0.0.1/private") is None


def test_gitfive_parser_only_accepts_result_section():
    assert parse_light("Login with operator@example.invalid") == []
    assert parse_light('Emails found for user "handle" :\n- input@example.invalid\n') == [
        "input@example.invalid"
    ]


def test_sparse_profiles_can_prompt_from_display_names():
    profiles = {
        key: normalize_profile(
            dict(
                id=key,
                platform="github",
                canonical_url=f"https://github.com/{key}",
                display_name=name,
            )
        )
        for key, name in [("a", "First Example"), ("b", "Second Example")]
    }
    hypotheses = tuple(HypothesisSnapshot(key, 0, "WEAK", (key,)) for key in profiles)
    plan = plan_disambiguation_question(hypotheses, profiles)
    assert plan.attribute == "display_name"
    assert plan.options[-1].value == "skip"
    assert plan.options[-2].value == "neither"


async def test_bounded_process_rejects_excess_output():
    with pytest.raises(ValueError, match="byte budget"):
        await run_process(sys.executable, "-c", "print('x'*20000)", max_bytes=100)


async def test_bounded_process_timeout():
    with pytest.raises(TimeoutError):
        await run_process(sys.executable, "-c", "import time; time.sleep(10)", budget_seconds=0.05)
