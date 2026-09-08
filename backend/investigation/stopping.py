"""Explicit, testable stopping rules for bounded investigations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StopReason(StrEnum):
    CONTINUE = "CONTINUE"
    AWAITING_USER = "AWAITING_USER"
    CANCELLED = "CANCELLED"
    SEARCH_DURATION_LIMIT = "SEARCH_DURATION_LIMIT"
    PIVOT_DEPTH_LIMIT = "PIVOT_DEPTH_LIMIT"
    CONNECTOR_RUN_LIMIT = "CONNECTOR_RUN_LIMIT"
    SUFFICIENT_EVIDENCE = "SUFFICIENT_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class StopDecision:
    should_stop: bool
    reason: StopReason


def evaluate_stopping(
    *,
    elapsed_seconds: float,
    max_duration_seconds: float,
    pivot_depth: int,
    max_pivot_depth: int,
    connector_runs: int,
    max_connector_runs: int,
    pending_question: bool,
    cancelled: bool = False,
    valuable_pivots_available: bool = False,
    leading_score: float | None = None,
    leading_margin: float | None = None,
) -> StopDecision:
    if cancelled:
        return StopDecision(True, StopReason.CANCELLED)
    if pending_question:
        return StopDecision(True, StopReason.AWAITING_USER)
    if elapsed_seconds >= max_duration_seconds:
        return StopDecision(True, StopReason.SEARCH_DURATION_LIMIT)
    if connector_runs >= max_connector_runs:
        return StopDecision(True, StopReason.CONNECTOR_RUN_LIMIT)
    if pivot_depth >= max_pivot_depth and valuable_pivots_available:
        return StopDecision(True, StopReason.PIVOT_DEPTH_LIMIT)
    if valuable_pivots_available:
        return StopDecision(False, StopReason.CONTINUE)
    if leading_score is not None and leading_score >= 0.45:
        if leading_margin is None or leading_margin >= 0.20:
            return StopDecision(True, StopReason.SUFFICIENT_EVIDENCE)
    return StopDecision(True, StopReason.INSUFFICIENT_EVIDENCE)
