"""Real-network round trip using an already observed avatar as its own reference.

This checks file reuse, not recognition or ownership. No photo fixtures are substituted.
"""

import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from backend.app.main import app
from backend.connectors.safe_http import fetch_public
from backend.db.models import ImageArtifact, ImageEmbedding
from backend.db.repositories import PostgresInvestigationRepository
from backend.db.session import AsyncSessionFactory, close_database


@pytest.mark.live
async def test_live_image_reuse_no_persistence():
    value = os.environ.get("DEUS_TEST_IMAGE_SEARCH_ID")
    if not value:
        pytest.skip("Set DEUS_TEST_IMAGE_SEARCH_ID to an actual existing search")
    try:
        async with AsyncSessionFactory() as session:
            repository = PostgresInvestigationRepository(session)
            profiles = await repository.list_profile_snapshots_for_search(UUID(value))
            candidates = [p for p in profiles if p.avatar_url]
            assert candidates, "Search has no collected public avatar to test"
            candidate = next((p for p in candidates if p.platform == "github"), candidates[0])
            before = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (ImageArtifact, ImageEmbedding)
            ]
        data, _, content_type = await fetch_public(
            candidate.avatar_url,
            max_bytes=5_000_000,
            allowed_types=("image/jpeg", "image/png", "image/webp"),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=70
        ) as client:
            response = await client.post(
                f"/api/searches/{value}/image-matches",
                content=data,
                headers={"Content-Type": content_type},
            )
        assert response.status_code == 200, response.text
        result = response.json()
        own = next(row for row in result["items"] if row["profile_id"] == str(candidate.id))
        assert own["status"] in {"EXACT_FILE", "SAME_PIXELS"}, own
        assert not result["identity_scores_changed"]
        async with AsyncSessionFactory() as session:
            after = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (ImageArtifact, ImageEmbedding)
            ]
        assert after == before
    finally:
        await close_database()
