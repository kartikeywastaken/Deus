"""Guarded extension point for a future AI investigation adviser.

The deterministic pipeline is authoritative in the MVP.  A later language-model
adapter may recommend a next action from structured state, but this module makes
the boundary explicit: it cannot create observations, set scores, or merge
profiles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class AgentAction(StrEnum):
    CONTINUE_SEARCH = "CONTINUE_SEARCH"
    RUN_CONNECTOR = "RUN_CONNECTOR"
    ASK_QUESTION = "ASK_QUESTION"
    STOP_SUFFICIENT_EVIDENCE = "STOP_SUFFICIENT_EVIDENCE"
    STOP_INSUFFICIENT_EVIDENCE = "STOP_INSUFFICIENT_EVIDENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True, slots=True)
class AgentRecommendation:
    action: AgentAction
    reason: str
    connector_name: str | None = None


class InvestigationAdviser(Protocol):
    async def recommend(self, structured_state: dict[str, Any]) -> AgentRecommendation: ...


class DisabledInvestigationAdviser:
    """Safe MVP default used until deterministic behavior is calibrated."""

    async def recommend(self, structured_state: dict[str, Any]) -> AgentRecommendation:
        del structured_state
        return AgentRecommendation(
            action=AgentAction.CONTINUE_SEARCH,
            reason="AI investigation advice is disabled for the deterministic MVP.",
        )
