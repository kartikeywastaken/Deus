"""PostgreSQL statements for image and bounded face vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.core.config import IMAGE_EMBEDDING_DIMENSION
from backend.core.enums import ImageEmbeddingType
from backend.db.models import ImageArtifact, ImageEmbedding, Profile
from backend.embeddings.text import _validated_vector


def image_embedding_upsert_statement(
    *,
    image_artifact_id: UUID,
    embedding_type: ImageEmbeddingType,
    model_name: str,
    model_version: str,
    embedding: Sequence[float],
    quality_score: float | None = None,
) -> Any:
    vector = _validated_vector(embedding, IMAGE_EMBEDDING_DIMENSION)
    statement = pg_insert(ImageEmbedding).values(
        id=uuid4(),
        image_artifact_id=image_artifact_id,
        embedding_type=embedding_type,
        model_name=model_name,
        model_version=model_version,
        embedding=vector,
        quality_score=quality_score,
    )
    return statement.on_conflict_do_update(
        constraint="uq_image_embeddings_artifact_type_model",
        set_={
            "embedding": statement.excluded.embedding,
            "quality_score": statement.excluded.quality_score,
        },
    ).returning(ImageEmbedding)


def image_similarity_statement(
    embedding: Sequence[float],
    *,
    embedding_type: ImageEmbeddingType = ImageEmbeddingType.GENERAL_IMAGE,
    limit: int = 10,
    model_name: str | None = None,
    model_version: str | None = None,
    platform: str | None = None,
    minimum_quality: float | None = None,
) -> Select:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    vector = _validated_vector(embedding, IMAGE_EMBEDDING_DIMENSION)
    distance = ImageEmbedding.embedding.cosine_distance(vector).label("distance")
    statement = (
        select(ImageEmbedding, distance)
        .join(ImageArtifact)
        .outerjoin(Profile, ImageArtifact.profile_id == Profile.id)
        .where(ImageEmbedding.embedding_type == embedding_type)
    )
    if model_name:
        statement = statement.where(ImageEmbedding.model_name == model_name)
    if model_version:
        statement = statement.where(ImageEmbedding.model_version == model_version)
    if platform:
        statement = statement.where(Profile.platform == platform.casefold())
    if minimum_quality is not None:
        if not 0 <= minimum_quality <= 1:
            raise ValueError("minimum_quality must be between 0 and 1")
        statement = statement.where(ImageEmbedding.quality_score >= minimum_quality)
    return statement.order_by(distance).limit(limit)
