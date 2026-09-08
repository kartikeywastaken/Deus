"""Small async repository dedicated to versioned pgvector operations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.enums import ImageEmbeddingType
from backend.db.models import ImageEmbedding, TextEmbedding

from .images import image_embedding_upsert_statement, image_similarity_statement
from .text import text_embedding_upsert_statement, text_similarity_statement


@dataclass(frozen=True, slots=True)
class VectorNeighbor:
    id: UUID
    owner_id: UUID
    distance: float
    model_name: str
    model_version: str


class PgVectorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_text(
        self,
        *,
        profile_id: UUID,
        source_field: str,
        model_name: str,
        model_version: str,
        embedding: Sequence[float],
    ) -> TextEmbedding:
        statement = text_embedding_upsert_statement(
            profile_id=profile_id,
            source_field=source_field,
            model_name=model_name,
            model_version=model_version,
            embedding=embedding,
        )
        return (await self.session.scalars(statement)).one()

    async def nearest_text(
        self,
        embedding: Sequence[float],
        **filters: object,
    ) -> list[VectorNeighbor]:
        rows = (await self.session.execute(text_similarity_statement(embedding, **filters))).all()
        return [
            VectorNeighbor(
                id=item.id,
                owner_id=item.profile_id,
                distance=float(distance),
                model_name=item.model_name,
                model_version=item.model_version,
            )
            for item, distance in rows
        ]

    async def upsert_image(
        self,
        *,
        image_artifact_id: UUID,
        embedding_type: ImageEmbeddingType,
        model_name: str,
        model_version: str,
        embedding: Sequence[float],
        quality_score: float | None = None,
    ) -> ImageEmbedding:
        statement = image_embedding_upsert_statement(
            image_artifact_id=image_artifact_id,
            embedding_type=embedding_type,
            model_name=model_name,
            model_version=model_version,
            embedding=embedding,
            quality_score=quality_score,
        )
        return (await self.session.scalars(statement)).one()

    async def nearest_images(
        self,
        embedding: Sequence[float],
        **filters: object,
    ) -> list[VectorNeighbor]:
        rows = (await self.session.execute(image_similarity_statement(embedding, **filters))).all()
        return [
            VectorNeighbor(
                id=item.id,
                owner_id=item.image_artifact_id,
                distance=float(distance),
                model_name=item.model_name,
                model_version=item.model_version,
            )
            for item, distance in rows
        ]
