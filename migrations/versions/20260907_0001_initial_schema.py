"""Create the PostgreSQL and pgvector identity-correlation schema.

Revision ID: 20260907_0001
Revises: None
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


uuid_type = postgresql.UUID(as_uuid=True)
empty_json_object = sa.text("'{}'::jsonb")
empty_json_array = sa.text("'[]'::jsonb")
empty_uuid_array = sa.text("'{}'::uuid[]")


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=64,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "search_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "status",
            string_enum(
                "search_status",
                "CREATED",
                "DISCOVERING",
                "NORMALIZING",
                "EXPANDING",
                "ENRICHING",
                "CORRELATING",
                "AWAITING_USER",
                "CONTINUING",
                "REPORTING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            ),
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column(
            "scope",
            string_enum("search_scope", "self_audit", "consented", "public_figure"),
            server_default="self_audit",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pivot_depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("questions_asked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("connector_runs_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_pivot_depth", sa.Integer(), server_default="3", nullable=False),
        sa.Column("max_questions", sa.Integer(), server_default="3", nullable=False),
        sa.Column("max_connector_runs", sa.Integer(), server_default="30", nullable=False),
        sa.Column("max_candidates", sa.Integer(), server_default="100", nullable=False),
        sa.Column(
            "max_search_duration_seconds", sa.Integer(), server_default="600", nullable=False
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint("pivot_depth >= 0", name="pivot_depth_nonnegative"),
        sa.CheckConstraint("questions_asked >= 0", name="questions_asked_nonnegative"),
        sa.CheckConstraint("connector_runs_count >= 0", name="connector_runs_count_nonnegative"),
        sa.CheckConstraint("max_pivot_depth >= 0", name="max_pivot_depth_nonnegative"),
        sa.CheckConstraint("max_questions >= 0", name="max_questions_nonnegative"),
        sa.CheckConstraint("max_connector_runs >= 1", name="max_connector_runs_positive"),
        sa.CheckConstraint("max_candidates >= 1", name="max_candidates_positive"),
        sa.CheckConstraint(
            "max_search_duration_seconds >= 1", name="max_search_duration_seconds_positive"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_search_runs"),
    )
    op.create_index("ix_search_runs_status", "search_runs", ["status"])

    op.create_table(
        "profiles",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("platform_account_id", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("normalized_username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=512), nullable=True),
        sa.Column("normalized_display_name", sa.String(length=512), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("current_bio", sa.Text(), nullable=True),
        sa.Column("current_location", sa.String(length=512), nullable=True),
        sa.Column("current_organization", sa.String(length=512), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_profiles"),
        sa.UniqueConstraint(
            "platform", "platform_account_id", name="uq_profiles_platform_account_id"
        ),
        sa.UniqueConstraint("platform", "canonical_url", name="uq_profiles_platform_canonical_url"),
    )
    op.create_index("ix_profiles_platform", "profiles", ["platform"])
    op.create_index("ix_profiles_normalized_username", "profiles", ["normalized_username"])
    op.create_index("ix_profiles_canonical_url", "profiles", ["canonical_url"])

    op.create_table(
        "image_artifacts",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("profile_id", uuid_type, nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=255), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="quality_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name="fk_image_artifacts_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_image_artifacts"),
    )
    op.create_index("ix_image_artifacts_profile_id", "image_artifacts", ["profile_id"])
    op.create_index("ix_image_artifacts_sha256", "image_artifacts", ["sha256"])
    op.create_index("ix_image_artifacts_perceptual_hash", "image_artifacts", ["perceptual_hash"])

    op.create_table(
        "search_seeds",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column(
            "seed_type",
            string_enum("seed_type", "USERNAME", "NAME", "PROFILE_URL", "IMAGE", "EMAIL", "PHONE"),
            nullable=False,
        ),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("artifact_id", uuid_type, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["image_artifacts.id"],
            name="fk_search_seeds_artifact_id_image_artifacts",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_search_seeds_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_search_seeds"),
    )
    op.create_index("ix_search_seeds_search_run_id", "search_seeds", ["search_run_id"])

    op.create_table(
        "connector_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column("connector", sa.String(length=128), nullable=False),
        sa.Column("connector_version", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            string_enum(
                "connector_status",
                "PENDING",
                "RUNNING",
                "SUCCESS",
                "PARTIAL",
                "NO_RESULTS",
                "RATE_LIMITED",
                "AUTH_REQUIRED",
                "UNAVAILABLE",
                "DISABLED",
                "FAILED",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "input_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.CheckConstraint("request_count >= 0", name="request_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_connector_runs_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connector_runs"),
    )
    op.create_index("ix_connector_runs_search_run_id", "connector_runs", ["search_run_id"])
    op.create_index("ix_connector_runs_status", "connector_runs", ["status"])

    op.create_table(
        "profile_observations",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column("profile_id", uuid_type, nullable=False),
        sa.Column("connector_run_id", uuid_type, nullable=False),
        sa.Column("connector", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "normalized_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_run_id"],
            ["connector_runs.id"],
            name="fk_profile_observations_connector_run_id_connector_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name="fk_profile_observations_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_profile_observations_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_profile_observations"),
    )
    op.create_index("ix_profile_observations_profile_id", "profile_observations", ["profile_id"])
    op.create_index(
        "ix_profile_observations_search_run_id", "profile_observations", ["search_run_id"]
    )
    op.create_index(
        "ix_profile_observations_connector_run_id", "profile_observations", ["connector_run_id"]
    )

    op.create_table(
        "identifiers",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("identifier_type", sa.String(length=64), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identifiers"),
        sa.UniqueConstraint(
            "identifier_type", "normalized_value", name="uq_identifiers_type_normalized_value"
        ),
    )
    op.create_index("ix_identifiers_normalized_value", "identifiers", ["normalized_value"])

    op.create_table(
        "profile_identifiers",
        sa.Column("profile_id", uuid_type, nullable=False),
        sa.Column("identifier_id", uuid_type, nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("observation_id", uuid_type, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["identifier_id"],
            ["identifiers.id"],
            name="fk_profile_identifiers_identifier_id_identifiers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["profile_observations.id"],
            name="fk_profile_identifiers_observation_id_profile_observations",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name="fk_profile_identifiers_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "identifier_id", "relationship_type", name="pk_profile_identifiers"
        ),
    )
    op.create_index("ix_profile_identifiers_profile_id", "profile_identifiers", ["profile_id"])
    op.create_index(
        "ix_profile_identifiers_identifier_id", "profile_identifiers", ["identifier_id"]
    )

    op.create_table(
        "profile_relationships",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("left_profile_id", uuid_type, nullable=False),
        sa.Column("right_profile_id", uuid_type, nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("left_profile_id <> right_profile_id", name="different_profiles"),
        sa.ForeignKeyConstraint(
            ["left_profile_id"],
            ["profiles.id"],
            name="fk_profile_relationships_left_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_profile_id"],
            ["profiles.id"],
            name="fk_profile_relationships_right_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_profile_relationships"),
        sa.UniqueConstraint(
            "left_profile_id",
            "right_profile_id",
            "relationship_type",
            name="uq_profile_relationships_pair_type",
        ),
    )
    op.create_index(
        "ix_profile_relationships_left_right",
        "profile_relationships",
        ["left_profile_id", "right_profile_id"],
    )

    op.create_table(
        "evidence_signals",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column("left_profile_id", uuid_type, nullable=False),
        sa.Column("right_profile_id", uuid_type, nullable=False),
        sa.Column("signal_type", sa.String(length=128), nullable=False),
        sa.Column(
            "direction",
            string_enum("evidence_direction", "SUPPORT", "CONTRADICT", "NEUTRAL"),
            nullable=False,
        ),
        sa.Column(
            "raw_value",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_object,
            nullable=False,
        ),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("model_contribution", sa.Float(), nullable=True),
        sa.Column("evidence_family", sa.String(length=128), nullable=False),
        sa.Column(
            "source_observation_ids",
            postgresql.ARRAY(uuid_type),
            server_default=empty_uuid_array,
            nullable=False,
        ),
        sa.Column("extractor_version", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("left_profile_id <> right_profile_id", name="different_profiles"),
        sa.CheckConstraint(
            "normalized_score >= 0 AND normalized_score <= 1", name="normalized_score_range"
        ),
        sa.CheckConstraint("reliability >= 0 AND reliability <= 1", name="reliability_range"),
        sa.ForeignKeyConstraint(
            ["left_profile_id"],
            ["profiles.id"],
            name="fk_evidence_signals_left_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_profile_id"],
            ["profiles.id"],
            name="fk_evidence_signals_right_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_evidence_signals_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_signals"),
    )
    op.create_index("ix_evidence_signals_search_run_id", "evidence_signals", ["search_run_id"])
    op.create_index(
        "ix_evidence_signals_left_right",
        "evidence_signals",
        ["left_profile_id", "right_profile_id"],
    )
    op.create_index("ix_evidence_signals_signal_type", "evidence_signals", ["signal_type"])
    op.create_index("ix_evidence_signals_evidence_family", "evidence_signals", ["evidence_family"])

    op.create_table(
        "identity_hypotheses",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column("label", sa.String(length=512), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column(
            "classification",
            string_enum("classification", "STRONG", "LIKELY", "AMBIGUOUS", "WEAK", "CONTRADICTORY"),
            nullable=False,
        ),
        sa.Column(
            "status",
            string_enum("hypothesis_status", "ACTIVE", "FINAL", "SUPERSEDED"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rank >= 1", name="rank_positive"),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_identity_hypotheses_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_hypotheses"),
        sa.UniqueConstraint("search_run_id", "rank", name="uq_identity_hypotheses_search_rank"),
    )
    op.create_index(
        "ix_identity_hypotheses_search_run_id", "identity_hypotheses", ["search_run_id"]
    )
    op.create_index(
        "ix_identity_hypotheses_search_rank", "identity_hypotheses", ["search_run_id", "rank"]
    )

    op.create_table(
        "hypothesis_memberships",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("hypothesis_id", uuid_type, nullable=False),
        sa.Column("profile_id", uuid_type, nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "classification",
            string_enum("classification", "STRONG", "LIKELY", "AMBIGUOUS", "WEAK", "CONTRADICTORY"),
            nullable=False,
        ),
        sa.Column("support_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("contradiction_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.CheckConstraint("support_count >= 0", name="support_count_nonnegative"),
        sa.CheckConstraint("contradiction_count >= 0", name="contradiction_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["identity_hypotheses.id"],
            name="fk_hypothesis_memberships_hypothesis_id_identity_hypotheses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name="fk_hypothesis_memberships_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hypothesis_memberships"),
        sa.UniqueConstraint(
            "hypothesis_id", "profile_id", name="uq_hypothesis_memberships_hypothesis_profile"
        ),
    )
    op.create_index(
        "ix_hypothesis_memberships_hypothesis_id", "hypothesis_memberships", ["hypothesis_id"]
    )
    op.create_index(
        "ix_hypothesis_memberships_profile_id", "hypothesis_memberships", ["profile_id"]
    )

    op.create_table(
        "investigation_questions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column(
            "question_type",
            string_enum("question_type", "YES_NO", "SINGLE_SELECT", "MULTI_SELECT"),
            nullable=False,
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=empty_json_array,
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "affected_profile_ids",
            postgresql.ARRAY(uuid_type),
            server_default=empty_uuid_array,
            nullable=False,
        ),
        sa.Column(
            "affected_hypothesis_ids",
            postgresql.ARRAY(uuid_type),
            server_default=empty_uuid_array,
            nullable=False,
        ),
        sa.Column("expected_information_gain", sa.Float(), nullable=True),
        sa.Column(
            "sensitivity_level",
            string_enum("sensitivity_level", "LOW", "MODERATE", "HIGH"),
            server_default="LOW",
            nullable=False,
        ),
        sa.Column(
            "status",
            string_enum("question_status", "PENDING", "ANSWERED", "SKIPPED", "EXPIRED"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expected_information_gain IS NULL OR expected_information_gain >= 0",
            name="information_gain_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_investigation_questions_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_questions"),
    )
    op.create_index(
        "ix_investigation_questions_search_run_id", "investigation_questions", ["search_run_id"]
    )
    op.create_index("ix_investigation_questions_status", "investigation_questions", ["status"])

    op.create_table(
        "investigation_answers",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("question_id", uuid_type, nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["investigation_questions.id"],
            name="fk_investigation_answers_question_id_investigation_questions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_answers"),
    )
    op.create_index(
        "ix_investigation_answers_question_id", "investigation_answers", ["question_id"]
    )

    op.create_table(
        "reports",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("search_run_id", uuid_type, nullable=False),
        sa.Column("report_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["search_runs.id"],
            name="fk_reports_search_run_id_search_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reports"),
    )
    op.create_index("ix_reports_search_run_id", "reports", ["search_run_id"])

    op.create_table(
        "text_embeddings",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("profile_id", uuid_type, nullable=False),
        sa.Column("source_field", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("embedding", Vector(dim=384), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name="fk_text_embeddings_profile_id_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_text_embeddings"),
        sa.UniqueConstraint(
            "profile_id",
            "source_field",
            "model_name",
            "model_version",
            name="uq_text_embeddings_source_model",
        ),
    )
    op.create_index("ix_text_embeddings_profile_id", "text_embeddings", ["profile_id"])

    op.create_table(
        "image_embeddings",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("image_artifact_id", uuid_type, nullable=False),
        sa.Column(
            "embedding_type",
            string_enum("image_embedding_type", "GENERAL_IMAGE", "FACE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("embedding", Vector(dim=512), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="quality_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["image_artifact_id"],
            ["image_artifacts.id"],
            name="fk_image_embeddings_image_artifact_id_image_artifacts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_image_embeddings"),
        sa.UniqueConstraint(
            "image_artifact_id",
            "embedding_type",
            "model_name",
            "model_version",
            name="uq_image_embeddings_artifact_type_model",
        ),
    )
    op.create_index(
        "ix_image_embeddings_image_artifact_id", "image_embeddings", ["image_artifact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_image_embeddings_image_artifact_id", table_name="image_embeddings")
    op.drop_table("image_embeddings")
    op.drop_index("ix_text_embeddings_profile_id", table_name="text_embeddings")
    op.drop_table("text_embeddings")
    op.drop_index("ix_reports_search_run_id", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_investigation_answers_question_id", table_name="investigation_answers")
    op.drop_table("investigation_answers")
    op.drop_index("ix_investigation_questions_status", table_name="investigation_questions")
    op.drop_index("ix_investigation_questions_search_run_id", table_name="investigation_questions")
    op.drop_table("investigation_questions")
    op.drop_index("ix_hypothesis_memberships_profile_id", table_name="hypothesis_memberships")
    op.drop_index("ix_hypothesis_memberships_hypothesis_id", table_name="hypothesis_memberships")
    op.drop_table("hypothesis_memberships")
    op.drop_index("ix_identity_hypotheses_search_rank", table_name="identity_hypotheses")
    op.drop_index("ix_identity_hypotheses_search_run_id", table_name="identity_hypotheses")
    op.drop_table("identity_hypotheses")
    op.drop_index("ix_evidence_signals_evidence_family", table_name="evidence_signals")
    op.drop_index("ix_evidence_signals_signal_type", table_name="evidence_signals")
    op.drop_index("ix_evidence_signals_left_right", table_name="evidence_signals")
    op.drop_index("ix_evidence_signals_search_run_id", table_name="evidence_signals")
    op.drop_table("evidence_signals")
    op.drop_index("ix_profile_relationships_left_right", table_name="profile_relationships")
    op.drop_table("profile_relationships")
    op.drop_index("ix_profile_identifiers_identifier_id", table_name="profile_identifiers")
    op.drop_index("ix_profile_identifiers_profile_id", table_name="profile_identifiers")
    op.drop_table("profile_identifiers")
    op.drop_index("ix_identifiers_normalized_value", table_name="identifiers")
    op.drop_table("identifiers")
    op.drop_index("ix_profile_observations_connector_run_id", table_name="profile_observations")
    op.drop_index("ix_profile_observations_search_run_id", table_name="profile_observations")
    op.drop_index("ix_profile_observations_profile_id", table_name="profile_observations")
    op.drop_table("profile_observations")
    op.drop_index("ix_connector_runs_status", table_name="connector_runs")
    op.drop_index("ix_connector_runs_search_run_id", table_name="connector_runs")
    op.drop_table("connector_runs")
    op.drop_index("ix_search_seeds_search_run_id", table_name="search_seeds")
    op.drop_table("search_seeds")
    op.drop_index("ix_image_artifacts_perceptual_hash", table_name="image_artifacts")
    op.drop_index("ix_image_artifacts_sha256", table_name="image_artifacts")
    op.drop_index("ix_image_artifacts_profile_id", table_name="image_artifacts")
    op.drop_table("image_artifacts")
    op.drop_index("ix_profiles_canonical_url", table_name="profiles")
    op.drop_index("ix_profiles_normalized_username", table_name="profiles")
    op.drop_index("ix_profiles_platform", table_name="profiles")
    op.drop_table("profiles")
    op.drop_index("ix_search_runs_status", table_name="search_runs")
    op.drop_table("search_runs")
    op.execute("DROP EXTENSION IF EXISTS vector")
