"""Allow planner decisions without pretending they are user answers."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0005"
down_revision = "20260908_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("user_search_context", "question_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("user_search_context", "answer_id", existing_type=sa.Uuid(), nullable=True)


def downgrade():
    raise RuntimeError("Archive planner-only context before restoring non-null answer constraints")
