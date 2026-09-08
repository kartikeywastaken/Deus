"""Content-addressed text embedding cache."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0004"
down_revision = "20260908_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("text_embeddings", sa.Column("content_hash", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("text_embeddings", "content_hash")
