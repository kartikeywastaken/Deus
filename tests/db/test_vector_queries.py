"""Compile pgvector writes and restricted similarity reads without a live server."""

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from backend.core.config import IMAGE_EMBEDDING_DIMENSION, TEXT_EMBEDDING_DIMENSION
from backend.core.enums import ImageEmbeddingType
from backend.embeddings import (
    image_embedding_upsert_statement,
    image_similarity_statement,
    text_embedding_upsert_statement,
    text_similarity_statement,
)


def test_text_embedding_upsert_and_restricted_nearest_query_compile() -> None:
    vector = [0.0] * TEXT_EMBEDDING_DIMENSION
    vector[0] = 1.0
    upsert_sql = str(
        text_embedding_upsert_statement(
            profile_id=uuid4(),
            source_field="bio",
            model_name="fixture-model",
            model_version="v1",
            embedding=vector,
        ).compile(dialect=postgresql.dialect())
    )
    nearest_sql = str(
        text_similarity_statement(
            vector,
            model_name="fixture-model",
            model_version="v1",
            source_field="bio",
            platform="github",
        ).compile(dialect=postgresql.dialect())
    )

    assert "ON CONFLICT ON CONSTRAINT uq_text_embeddings_source_model" in upsert_sql
    assert "<=>" in nearest_sql
    assert "profiles.platform" in nearest_sql
    assert "text_embeddings.model_version" in nearest_sql


def test_image_embedding_upsert_and_quality_restricted_query_compile() -> None:
    vector = [0.0] * IMAGE_EMBEDDING_DIMENSION
    vector[0] = 1.0
    upsert_sql = str(
        image_embedding_upsert_statement(
            image_artifact_id=uuid4(),
            embedding_type=ImageEmbeddingType.FACE,
            model_name="fixture-face-model",
            model_version="v1",
            embedding=vector,
            quality_score=0.9,
        ).compile(dialect=postgresql.dialect())
    )
    nearest_sql = str(
        image_similarity_statement(
            vector,
            embedding_type=ImageEmbeddingType.FACE,
            minimum_quality=0.8,
        ).compile(dialect=postgresql.dialect())
    )

    assert "ON CONFLICT ON CONSTRAINT uq_image_embeddings_artifact_type_model" in upsert_sql
    assert "<=>" in nearest_sql
    assert "image_embeddings.quality_score" in nearest_sql


def test_vector_length_is_validated_before_database_call() -> None:
    with pytest.raises(ValueError, match="exactly 384"):
        text_similarity_statement([0.0, 1.0])
