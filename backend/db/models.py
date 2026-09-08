"""SQLAlchemy models for the PostgreSQL identity-correlation store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum as PythonEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.core.config import IMAGE_EMBEDDING_DIMENSION, TEXT_EMBEDDING_DIMENSION
from backend.core.enums import (
    Classification,
    ConnectorStatus,
    EvidenceDirection,
    HypothesisStatus,
    ImageEmbeddingType,
    QuestionStatus,
    QuestionType,
    SearchScope,
    SearchStatus,
    SeedType,
    SensitivityLevel,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with deterministic constraint names for Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""

    return datetime.now(UTC)


def _string_enum(enum_class: type[PythonEnum], name: str) -> Enum:
    """Persist string enum values in VARCHAR columns with database checks."""

    return Enum(
        enum_class,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
        length=64,
        name=name,
    )


class SearchRun(Base):
    __tablename__ = "search_runs"
    __table_args__ = (
        CheckConstraint("pivot_depth >= 0", name="pivot_depth_nonnegative"),
        CheckConstraint("questions_asked >= 0", name="questions_asked_nonnegative"),
        CheckConstraint("connector_runs_count >= 0", name="connector_runs_count_nonnegative"),
        CheckConstraint("max_pivot_depth >= 0", name="max_pivot_depth_nonnegative"),
        CheckConstraint("max_questions >= 0", name="max_questions_nonnegative"),
        CheckConstraint("max_connector_runs >= 1", name="max_connector_runs_positive"),
        CheckConstraint("max_candidates >= 1", name="max_candidates_positive"),
        CheckConstraint(
            "max_search_duration_seconds >= 1", name="max_search_duration_seconds_positive"
        ),
        Index("ix_search_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[SearchStatus] = mapped_column(
        _string_enum(SearchStatus, "search_status"),
        default=SearchStatus.CREATED,
        server_default=SearchStatus.CREATED.value,
    )
    scope: Mapped[SearchScope] = mapped_column(
        _string_enum(SearchScope, "search_scope"),
        default=SearchScope.SELF_AUDIT,
        server_default=SearchScope.SELF_AUDIT.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pivot_depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    questions_asked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    connector_runs_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_pivot_depth: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    max_questions: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    max_connector_runs: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    max_candidates: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    max_search_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=600, server_default="600"
    )
    error_summary: Mapped[str | None] = mapped_column(Text)

    seeds: Mapped[list[SearchSeed]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )
    connector_runs: Mapped[list[ConnectorRun]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )
    observations: Mapped[list[ProfileObservation]] = relationship(back_populates="search_run")
    evidence_signals: Mapped[list[EvidenceSignal]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list[IdentityHypothesis]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )
    questions: Mapped[list[InvestigationQuestion]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("platform", "platform_account_id", name="uq_profiles_platform_account_id"),
        UniqueConstraint("platform", "canonical_url", name="uq_profiles_platform_canonical_url"),
        Index("ix_profiles_platform", "platform"),
        Index("ix_profiles_normalized_username", "normalized_username"),
        Index("ix_profiles_canonical_url", "canonical_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(64))
    platform_account_id: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    normalized_username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(512))
    normalized_display_name: Mapped[str | None] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    current_bio: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(String(512))
    current_organization: Mapped[str | None] = mapped_column(String(512))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    observations: Mapped[list[ProfileObservation]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    identifier_links: Mapped[list[ProfileIdentifier]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    memberships: Mapped[list[HypothesisMembership]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    image_artifacts: Mapped[list[ImageArtifact]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    text_embeddings: Mapped[list[TextEmbedding]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ImageArtifact(Base):
    __tablename__ = "image_artifacts"
    __table_args__ = (
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="quality_score_range",
        ),
        Index("ix_image_artifacts_profile_id", "profile_id"),
        Index("ix_image_artifacts_sha256", "sha256"),
        Index("ix_image_artifacts_perceptual_hash", "perceptual_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    perceptual_hash: Mapped[str | None] = mapped_column(String(255))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    profile: Mapped[Profile | None] = relationship(back_populates="image_artifacts")
    embeddings: Mapped[list[ImageEmbedding]] = relationship(
        back_populates="image_artifact", cascade="all, delete-orphan"
    )


class SearchSeed(Base):
    __tablename__ = "search_seeds"
    __table_args__ = (Index("ix_search_seeds_search_run_id", "search_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    seed_type: Mapped[SeedType] = mapped_column(_string_enum(SeedType, "seed_type"))
    original_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("image_artifacts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="seeds")
    artifact: Mapped[ImageArtifact | None] = relationship()


class ConnectorRun(Base):
    __tablename__ = "connector_runs"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="request_count_nonnegative"),
        Index("ix_connector_runs_search_run_id", "search_run_id"),
        Index("ix_connector_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    connector: Mapped[str] = mapped_column(String(128))
    connector_version: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[ConnectorStatus] = mapped_column(
        _string_enum(ConnectorStatus, "connector_status"),
        default=ConnectorStatus.PENDING,
        server_default=ConnectorStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="connector_runs")
    observations: Mapped[list[ProfileObservation]] = relationship(back_populates="connector_run")


class ProfileObservation(Base):
    __tablename__ = "profile_observations"
    __table_args__ = (
        Index("ix_profile_observations_profile_id", "profile_id"),
        Index("ix_profile_observations_search_run_id", "search_run_id"),
        Index("ix_profile_observations_connector_run_id", "connector_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    connector_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("connector_runs.id", ondelete="CASCADE")
    )
    connector: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    normalized_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    content_hash: Mapped[str | None] = mapped_column(String(64))

    search_run: Mapped[SearchRun] = relationship(back_populates="observations")
    profile: Mapped[Profile] = relationship(back_populates="observations")
    connector_run: Mapped[ConnectorRun] = relationship(back_populates="observations")


class Identifier(Base):
    __tablename__ = "identifiers"
    __table_args__ = (
        UniqueConstraint(
            "identifier_type", "normalized_value", name="uq_identifiers_type_normalized_value"
        ),
        Index("ix_identifiers_normalized_value", "normalized_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier_type: Mapped[str] = mapped_column(String(64))
    normalized_value: Mapped[str] = mapped_column(Text)
    display_value: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    profile_links: Mapped[list[ProfileIdentifier]] = relationship(
        back_populates="identifier", cascade="all, delete-orphan"
    )


class ProfileIdentifier(Base):
    __tablename__ = "profile_identifiers"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_profile_identifiers_profile_id", "profile_id"),
        Index("ix_profile_identifiers_identifier_id", "identifier_id"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    identifier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profile_observations.id", ondelete="SET NULL")
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    profile: Mapped[Profile] = relationship(back_populates="identifier_links")
    identifier: Mapped[Identifier] = relationship(back_populates="profile_links")
    observation: Mapped[ProfileObservation | None] = relationship()


class ProfileRelationship(Base):
    __tablename__ = "profile_relationships"
    __table_args__ = (
        CheckConstraint("left_profile_id <> right_profile_id", name="different_profiles"),
        UniqueConstraint(
            "left_profile_id",
            "right_profile_id",
            "relationship_type",
            name="uq_profile_relationships_pair_type",
        ),
        Index("ix_profile_relationships_left_right", "left_profile_id", "right_profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    left_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    right_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    relationship_type: Mapped[str] = mapped_column(String(64))
    raw_score: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    left_profile: Mapped[Profile] = relationship(foreign_keys=[left_profile_id])
    right_profile: Mapped[Profile] = relationship(foreign_keys=[right_profile_id])


class EvidenceSignal(Base):
    __tablename__ = "evidence_signals"
    __table_args__ = (
        CheckConstraint("left_profile_id <> right_profile_id", name="different_profiles"),
        CheckConstraint(
            "normalized_score >= 0 AND normalized_score <= 1", name="normalized_score_range"
        ),
        CheckConstraint("reliability >= 0 AND reliability <= 1", name="reliability_range"),
        Index("ix_evidence_signals_search_run_id", "search_run_id"),
        Index("ix_evidence_signals_left_right", "left_profile_id", "right_profile_id"),
        Index("ix_evidence_signals_signal_type", "signal_type"),
        Index("ix_evidence_signals_evidence_family", "evidence_family"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    left_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    right_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    signal_type: Mapped[str] = mapped_column(String(128))
    direction: Mapped[EvidenceDirection] = mapped_column(
        _string_enum(EvidenceDirection, "evidence_direction")
    )
    raw_value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    normalized_score: Mapped[float] = mapped_column(Float)
    reliability: Mapped[float] = mapped_column(Float)
    model_contribution: Mapped[float | None] = mapped_column(Float)
    evidence_family: Mapped[str] = mapped_column(String(128))
    source_observation_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid(as_uuid=True)), default=list, server_default="{}"
    )
    extractor_version: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="evidence_signals")
    left_profile: Mapped[Profile] = relationship(foreign_keys=[left_profile_id])
    right_profile: Mapped[Profile] = relationship(foreign_keys=[right_profile_id])


class IdentityHypothesis(Base):
    __tablename__ = "identity_hypotheses"
    __table_args__ = (
        Index("ix_identity_hypotheses_search_run_id", "search_run_id"),
        CheckConstraint("rank >= 1", name="rank_positive"),
        UniqueConstraint("search_run_id", "rank", name="uq_identity_hypotheses_search_rank"),
        Index("ix_identity_hypotheses_search_rank", "search_run_id", "rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(512))
    rank: Mapped[int] = mapped_column(Integer)
    overall_score: Mapped[float] = mapped_column(Float)
    classification: Mapped[Classification] = mapped_column(
        _string_enum(Classification, "classification")
    )
    status: Mapped[HypothesisStatus] = mapped_column(
        _string_enum(HypothesisStatus, "hypothesis_status"),
        default=HypothesisStatus.ACTIVE,
        server_default=HypothesisStatus.ACTIVE.value,
    )
    model_version: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), onupdate=utc_now
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="hypotheses")
    memberships: Mapped[list[HypothesisMembership]] = relationship(
        back_populates="hypothesis", cascade="all, delete-orphan"
    )


class HypothesisMembership(Base):
    __tablename__ = "hypothesis_memberships"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_id", "profile_id", name="uq_hypothesis_memberships_hypothesis_profile"
        ),
        CheckConstraint("support_count >= 0", name="support_count_nonnegative"),
        CheckConstraint("contradiction_count >= 0", name="contradiction_count_nonnegative"),
        Index("ix_hypothesis_memberships_hypothesis_id", "hypothesis_id"),
        Index("ix_hypothesis_memberships_profile_id", "profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("identity_hypotheses.id", ondelete="CASCADE")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    score: Mapped[float] = mapped_column(Float)
    classification: Mapped[Classification] = mapped_column(
        _string_enum(Classification, "classification")
    )
    support_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    model_version: Mapped[str] = mapped_column(String(128))

    hypothesis: Mapped[IdentityHypothesis] = relationship(back_populates="memberships")
    profile: Mapped[Profile] = relationship(back_populates="memberships")


class InvestigationQuestion(Base):
    __tablename__ = "investigation_questions"
    __table_args__ = (
        CheckConstraint(
            "expected_information_gain IS NULL OR expected_information_gain >= 0",
            name="information_gain_nonnegative",
        ),
        Index("ix_investigation_questions_search_run_id", "search_run_id"),
        Index("ix_investigation_questions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    question_type: Mapped[QuestionType] = mapped_column(_string_enum(QuestionType, "question_type"))
    question_text: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    reason: Mapped[str] = mapped_column(Text)
    affected_profile_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid(as_uuid=True)), default=list, server_default="{}"
    )
    affected_hypothesis_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid(as_uuid=True)), default=list, server_default="{}"
    )
    expected_information_gain: Mapped[float | None] = mapped_column(Float)
    sensitivity_level: Mapped[SensitivityLevel] = mapped_column(
        _string_enum(SensitivityLevel, "sensitivity_level"),
        default=SensitivityLevel.LOW,
        server_default=SensitivityLevel.LOW.value,
    )
    status: Mapped[QuestionStatus] = mapped_column(
        _string_enum(QuestionStatus, "question_status"),
        default=QuestionStatus.PENDING,
        server_default=QuestionStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    search_run: Mapped[SearchRun] = relationship(back_populates="questions")
    answers: Mapped[list[InvestigationAnswer]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class InvestigationAnswer(Base):
    __tablename__ = "investigation_answers"
    __table_args__ = (Index("ix_investigation_answers_question_id", "question_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_questions.id", ondelete="CASCADE")
    )
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    question: Mapped[InvestigationQuestion] = relationship(back_populates="answers")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_search_run_id", "search_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("search_runs.id", ondelete="CASCADE")
    )
    report_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="reports")


class TextEmbedding(Base):
    __tablename__ = "text_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "source_field",
            "model_name",
            "model_version",
            name="uq_text_embeddings_source_model",
        ),
        Index("ix_text_embeddings_profile_id", "profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    source_field: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(255))
    model_version: Mapped[str] = mapped_column(String(128))
    embedding: Mapped[list[float]] = mapped_column(Vector(TEXT_EMBEDDING_DIMENSION))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    profile: Mapped[Profile] = relationship(back_populates="text_embeddings")


class ImageEmbedding(Base):
    __tablename__ = "image_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "image_artifact_id",
            "embedding_type",
            "model_name",
            "model_version",
            name="uq_image_embeddings_artifact_type_model",
        ),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="quality_score_range",
        ),
        Index("ix_image_embeddings_image_artifact_id", "image_artifact_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_artifact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("image_artifacts.id", ondelete="CASCADE")
    )
    embedding_type: Mapped[ImageEmbeddingType] = mapped_column(
        _string_enum(ImageEmbeddingType, "image_embedding_type")
    )
    model_name: Mapped[str] = mapped_column(String(255))
    model_version: Mapped[str] = mapped_column(String(128))
    embedding: Mapped[list[float]] = mapped_column(Vector(IMAGE_EMBEDDING_DIMENSION))
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    image_artifact: Mapped[ImageArtifact] = relationship(back_populates="embeddings")


__all__ = [
    "Base",
    "ConnectorRun",
    "EvidenceSignal",
    "HypothesisMembership",
    "Identifier",
    "IdentityHypothesis",
    "ImageArtifact",
    "ImageEmbedding",
    "InvestigationAnswer",
    "InvestigationQuestion",
    "Profile",
    "ProfileIdentifier",
    "ProfileObservation",
    "ProfileRelationship",
    "Report",
    "SearchRun",
    "SearchSeed",
    "TextEmbedding",
]
