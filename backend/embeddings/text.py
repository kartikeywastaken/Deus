"""PostgreSQL statements for versioned biography/text vectors."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.core.config import TEXT_EMBEDDING_DIMENSION
from backend.db.models import Profile, TextEmbedding


def text_embedding_upsert_statement(
    *,
    profile_id: UUID,
    source_field: str,
    model_name: str,
    model_version: str,
    embedding: Sequence[float],
) -> Any:
    vector = _validated_vector(embedding, TEXT_EMBEDDING_DIMENSION)
    statement = pg_insert(TextEmbedding).values(
        id=uuid4(),
        profile_id=profile_id,
        source_field=source_field,
        model_name=model_name,
        model_version=model_version,
        embedding=vector,
    )
    return statement.on_conflict_do_update(
        constraint="uq_text_embeddings_source_model",
        set_={"embedding": statement.excluded.embedding},
    ).returning(TextEmbedding)


def text_similarity_statement(
    embedding: Sequence[float],
    *,
    limit: int = 10,
    model_name: str | None = None,
    model_version: str | None = None,
    source_field: str | None = None,
    platform: str | None = None,
) -> Select:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    vector = _validated_vector(embedding, TEXT_EMBEDDING_DIMENSION)
    distance = TextEmbedding.embedding.cosine_distance(vector).label("distance")
    statement = select(TextEmbedding, distance).join(Profile)
    if model_name:
        statement = statement.where(TextEmbedding.model_name == model_name)
    if model_version:
        statement = statement.where(TextEmbedding.model_version == model_version)
    if source_field:
        statement = statement.where(TextEmbedding.source_field == source_field)
    if platform:
        statement = statement.where(Profile.platform == platform.casefold())
    return statement.order_by(distance).limit(limit)


def _validated_vector(values: Sequence[float], dimension: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != dimension:
        raise ValueError(f"embedding must contain exactly {dimension} values")
    if not all(math.isfinite(v) for v in vector) or not any(vector):
        raise ValueError("embedding must be finite and nonzero")
    return vector
