"""Deterministic next-best-action selection over actual persisted work."""

from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    RUN_CONNECTOR = "RUN_CONNECTOR"
    RUN_PIVOT = "RUN_PIVOT"
    ASK_QUESTION = "ASK_QUESTION"
    CORRELATE = "CORRELATE"
    STOP_SUFFICIENT = "STOP_SUFFICIENT"
    STOP_INSUFFICIENT = "STOP_INSUFFICIENT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class Decision:
    kind: Action
    reason: str
    pivots: tuple = ()
    question: dict | None = None


def choose_action(
    *,
    initial,
    hints,
    question,
    enrichment,
    runs_remaining,
    questions_remaining,
    pivot_remaining,
    leading_score,
):
    if runs_remaining > 0:
        if initial:
            return Decision(
                Action.RUN_CONNECTOR, "Collect the unsearched seed.", initial[:runs_remaining]
            )
        if hints and pivot_remaining > 0:
            return Decision(
                Action.RUN_PIVOT,
                "Search observed usernames or operator clues live.",
                hints[:runs_remaining],
            )
        if question and questions_remaining > 0 and pivot_remaining > 0:
            return Decision(
                Action.ASK_QUESTION,
                "A short answer chooses a smaller search branch.",
                question=question,
            )
        if enrichment and pivot_remaining > 0:
            return Decision(
                Action.RUN_PIVOT,
                "Enrich relevant candidates, not all similar handles.",
                enrichment[:runs_remaining],
            )
    return Decision(
        Action.STOP_SUFFICIENT if leading_score >= 0.45 else Action.STOP_INSUFFICIENT,
        "No higher-value eligible work remains within the search budget.",
    )
