from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.enums import SeedType


class SearchCreate(BaseModel):
    seed_type: SeedType = SeedType.USERNAME
    value: str = Field(min_length=1, max_length=500)
    scope: str = Field(default="self_audit", pattern="^(self_audit|consented|public_figure)$")
    email_self_audit_confirmed: bool = False

    @field_validator("seed_type", mode="before")
    @classmethod
    def normalize_seed_type(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class SearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    scope: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    pivot_depth: int
    questions_asked: int
    connector_runs_count: int
    max_pivot_depth: int
    max_questions: int
    max_connector_runs: int
    max_candidates: int
    max_search_duration_seconds: int
    error_summary: str | None = None


class CandidateRead(BaseModel):
    id: UUID
    platform: str
    username: str | None
    display_name: str | None
    canonical_url: str
    score: float | None = None
    identity_score: float | None = None
    seed_match_bonus: float = 0.0
    hint_match_bonus: float = 0.0
    score_kind: str = "SEARCH_RELEVANCE"
    classification: str | None = None
    relevance: str | None = None
    reason: str | None = None


class CandidateList(BaseModel):
    items: list[CandidateRead]


class EvidenceRead(BaseModel):
    id: UUID
    left_profile_id: UUID
    right_profile_id: UUID
    signal_type: str
    direction: str
    normalized_score: float
    reliability: float
    model_contribution: float | None
    evidence_family: str
    explanation: str


class EvidenceList(BaseModel):
    items: list[EvidenceRead]


class MembershipRead(BaseModel):
    profile_id: UUID
    score: float
    classification: str
    support_count: int
    contradiction_count: int


class HypothesisRead(BaseModel):
    id: UUID
    rank: int
    overall_score: float
    classification: str
    memberships: list[MembershipRead]


class HypothesisList(BaseModel):
    items: list[HypothesisRead]


class QuestionOption(BaseModel):
    value: str
    label: str
    hypothesis_id: UUID | None = None
    profile_ids: list[UUID] = Field(default_factory=list)


class QuestionRead(BaseModel):
    id: UUID
    question_type: str
    question_text: str
    options: list[QuestionOption]
    reason: str
    expected_information_gain: float | None
    sensitivity_level: str
    status: str
    context: dict[str, Any] = Field(default_factory=dict)


class QuestionEnvelope(BaseModel):
    item: QuestionRead | None


class QuestionAnswerCreate(BaseModel):
    question_id: UUID
    value: str | list[str] = Field(min_length=1, max_length=500)


class ReportEnvelope(BaseModel):
    report_data: dict[str, Any] | None


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    score: float | None = None
    classification: str | None = None


class GraphRead(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
