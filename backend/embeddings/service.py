"""Real local embeddings, cached by exact observed text and pinned model revision."""

import asyncio
import hashlib
from dataclasses import replace
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select

from backend.db.models import TextEmbedding
from backend.embeddings.text import text_embedding_upsert_statement

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL, revision=REVISION, trust_remote_code=False, device="cpu")


def encode(texts):
    return model().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


async def enrich_bios(session, profiles):
    """Only profiles and observations already in this search can form neighbor pairs."""
    enriched, neighbors = [], []
    for profile in profiles:
        if not profile.bio or len(profile.bio.strip()) < 20:
            enriched.append(profile)
            continue
        content = profile.bio.strip()[:4000]
        digest = hashlib.sha256(content.encode()).hexdigest()
        row = await session.scalar(
            select(TextEmbedding).where(
                TextEmbedding.profile_id == UUID(profile.profile_id),
                TextEmbedding.source_field == "bio",
                TextEmbedding.model_name == MODEL,
                TextEmbedding.model_version == REVISION,
            )
        )
        if row is None or row.content_hash != digest:
            vector = (await asyncio.to_thread(encode, [content]))[0]
            row = (
                await session.scalars(
                    text_embedding_upsert_statement(
                        profile_id=UUID(profile.profile_id),
                        source_field="bio",
                        model_name=MODEL,
                        model_version=REVISION,
                        embedding=vector,
                    )
                )
            ).one()
            row.content_hash = digest
            await session.flush()
        enriched.append(replace(profile, bio_embedding=tuple(float(v) for v in row.embedding)))
    ids = [UUID(p.profile_id) for p in enriched if p.bio_embedding]
    for profile in enriched:
        if not profile.bio_embedding:
            continue
        distance = TextEmbedding.embedding.cosine_distance(list(profile.bio_embedding))
        rows = await session.scalars(
            select(TextEmbedding.profile_id)
            .where(
                TextEmbedding.profile_id.in_(ids),
                TextEmbedding.profile_id != UUID(profile.profile_id),
                TextEmbedding.source_field == "bio",
                TextEmbedding.model_name == MODEL,
                TextEmbedding.model_version == REVISION,
                distance < 0.25,
            )
            .order_by(distance)
            .limit(5)
        )
        neighbors.extend((profile.profile_id, str(other)) for other in rows)
    return tuple(enriched), neighbors
