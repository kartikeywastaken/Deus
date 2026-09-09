from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReportProfile(BaseModel):
    id: UUID
    platform: str
    username: str | None = None
    display_name: str | None = None
    canonical_url: str
    score: float
    classification: str


class ReportHypothesis(BaseModel):
    id: UUID
    rank: int
    score: float
    classification: str
    profiles: list[ReportProfile]


class ReportEvidence(BaseModel):
    signal_type: str
    direction: str
    explanation: str
    normalized_score: float
    reliability: float
    source_urls: list[str] = Field(default_factory=list)


class RankedReport(BaseModel):
    search_run_id: UUID
    executive_finding: str
    primary_hypothesis: ReportHypothesis | None
    alternative_hypotheses: list[ReportHypothesis] = Field(default_factory=list)
    supporting_evidence: list[ReportEvidence] = Field(default_factory=list)
    moderate_evidence: list[ReportEvidence] = Field(default_factory=list)
    contradictions: list[ReportEvidence] = Field(default_factory=list)
    source_provenance: list[dict[str, Any]] = Field(default_factory=list)
    questions_asked: list[dict[str, Any]] = Field(default_factory=list)
    answer_impact: list[str] = Field(default_factory=list)
    unavailable_connectors: list[str] = Field(default_factory=list)
    connector_runs: list[dict[str, Any]] = Field(default_factory=list)
    lead_candidates: list[dict[str, Any]] = Field(default_factory=list)
    self_audit_findings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    suggested_next_public_sources: list[str] = Field(default_factory=list)
