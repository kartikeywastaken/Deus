"""pgvector persistence and nearest-neighbour query helpers."""

from .images import image_embedding_upsert_statement, image_similarity_statement
from .repository import PgVectorRepository, VectorNeighbor
from .text import text_embedding_upsert_statement, text_similarity_statement

__all__ = [
    "PgVectorRepository",
    "VectorNeighbor",
    "image_embedding_upsert_statement",
    "image_similarity_statement",
    "text_embedding_upsert_statement",
    "text_similarity_statement",
]
