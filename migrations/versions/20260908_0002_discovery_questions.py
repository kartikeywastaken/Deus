"""Persist structured discovery questions and bounded text answers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260908_0002"
down_revision = "20260907_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "investigation_questions",
        sa.Column(
            "context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'ck_investigation_questions_question_type'
            AND conrelid = 'investigation_questions'::regclass
        ) THEN
            ALTER TABLE investigation_questions
            DROP CONSTRAINT ck_investigation_questions_question_type;
        END IF;
    END $$;
    """)
    op.create_check_constraint(
        op.f("ck_investigation_questions_question_type"),
        "investigation_questions",
        "question_type IN ('YES_NO','SINGLE_SELECT','MULTI_SELECT','TEXT')",
    )


def downgrade():
    # Preserve stored answers; refuse a lossy downgrade when text questions exist.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM investigation_questions WHERE question_type='TEXT'")
    ):
        raise RuntimeError("Cannot downgrade while text questions exist.")
    op.drop_constraint(
        op.f("ck_investigation_questions_question_type"), "investigation_questions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_investigation_questions_question_type"),
        "investigation_questions",
        "question_type IN ('YES_NO','SINGLE_SELECT','MULTI_SELECT')",
    )
    op.drop_column("investigation_questions", "context")
