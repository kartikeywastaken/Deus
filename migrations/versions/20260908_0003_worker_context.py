"""Durable PostgreSQL jobs and auditable user hints."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260908_0003"
down_revision = "20260908_0002"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "user_search_context",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column(
            "search_run_id",
            UUID(),
            sa.ForeignKey("search_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id", UUID(), sa.ForeignKey("investigation_questions.id"), nullable=False
        ),
        sa.Column(
            "answer_id",
            UUID(),
            sa.ForeignKey("investigation_answers.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("context_type", sa.String(64), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_search_context_search_run_id", "user_search_context", ["search_run_id"]
    )
    op.create_table(
        "investigation_jobs",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column(
            "search_run_id",
            UUID(),
            sa.ForeignKey("search_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("runtime_seconds", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','WAITING','COMPLETED','FAILED','CANCELLED')",
            name="job_status",
        ),
    )
    op.create_index("ix_investigation_jobs_search_run_id", "investigation_jobs", ["search_run_id"])
    op.create_index("ix_jobs_claim", "investigation_jobs", ["status", "available_at"])
    op.drop_constraint(op.f("ck_connector_runs_connector_status"), "connector_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_connector_runs_connector_status"),
        "connector_runs",
        "status IN ('PENDING','RUNNING','SUCCESS','PARTIAL','NO_RESULTS','RATE_LIMITED','AUTH_REQUIRED','UNAVAILABLE','DISABLED','FAILED','MANUAL')",
    )


def downgrade():
    raise RuntimeError(
        "This migration preserves job and user-context history; downgrade requires an explicit data migration."
    )
