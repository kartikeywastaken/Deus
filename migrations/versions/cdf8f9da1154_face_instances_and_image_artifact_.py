"""Add face_instances table and extend image_artifacts with face columns.

Revision ID: 20260910_0007
Revises: 20260909_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0007"
down_revision: str | None = "20260909_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

uuid_type = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    # ── Extend image_artifacts ─────────────────────────────────────────────
    op.add_column("image_artifacts", sa.Column("search_run_id", uuid_type, nullable=True))
    op.add_column("image_artifacts", sa.Column("artifact_role", sa.String(32), nullable=True))
    op.add_column("image_artifacts", sa.Column("face_count", sa.Integer, nullable=True))
    op.add_column("image_artifacts", sa.Column("face_status", sa.String(32), nullable=True))
    op.add_column(
        "image_artifacts",
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("exif_metadata", sa.dialects.postgresql.JSONB, nullable=True, server_default="{}"),
    )
    # Extend perceptual_hash column to hold all hash algorithms JSON
    op.add_column(
        "image_artifacts",
        sa.Column("phash", sa.String(32), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("dhash", sa.String(32), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("colorhash", sa.String(32), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("whash", sa.String(32), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("crop_resistant_hash", sa.Text, nullable=True),
    )
    op.create_foreign_key(
        "fk_image_artifacts_search_run_id_search_runs",
        "image_artifacts",
        "search_runs",
        ["search_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_image_artifacts_search_run_id", "image_artifacts", ["search_run_id"]
    )
    op.create_index(
        "ix_image_artifacts_artifact_role", "image_artifacts", ["artifact_role"]
    )

    # ── face_instances ─────────────────────────────────────────────────────
    op.create_table(
        "face_instances",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "image_artifact_id",
            uuid_type,
            sa.ForeignKey("image_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("face_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bounding_box", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("detection_confidence", sa.Float, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("pose_metadata", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column(
            "selected_for_reference",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_face_instances"),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="face_instances_quality_score_range",
        ),
        sa.CheckConstraint(
            "detection_confidence IS NULL OR (detection_confidence >= 0 AND detection_confidence <= 1)",
            name="face_instances_detection_confidence_range",
        ),
        sa.UniqueConstraint(
            "image_artifact_id", "face_index", name="uq_face_instances_artifact_face_index"
        ),
    )
    op.create_index(
        "ix_face_instances_image_artifact_id", "face_instances", ["image_artifact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_face_instances_image_artifact_id", table_name="face_instances")
    op.drop_table("face_instances")
    op.drop_index("ix_image_artifacts_artifact_role", table_name="image_artifacts")
    op.drop_index("ix_image_artifacts_search_run_id", table_name="image_artifacts")
    op.drop_constraint(
        "fk_image_artifacts_search_run_id_search_runs", "image_artifacts", type_="foreignkey"
    )
    for col in [
        "search_run_id", "artifact_role", "face_count", "face_status",
        "retention_expires_at", "exif_metadata",
        "phash", "dhash", "colorhash", "whash", "crop_resistant_hash",
    ]:
        op.drop_column("image_artifacts", col)
