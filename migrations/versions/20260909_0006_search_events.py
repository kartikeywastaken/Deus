"""Durable cursor-based server sent events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260909_0006"
down_revision = "20260908_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "search_run_id",
            sa.Uuid(),
            sa.ForeignKey("search_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_events_cursor", "search_events", ["search_run_id", "id"])


def downgrade():
    op.drop_table("search_events")
