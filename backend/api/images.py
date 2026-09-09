"""Stateless image-reuse checks, deliberately outside identity scoring."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_repository
from backend.db.repositories import PostgresInvestigationRepository
from backend.image_reuse import MAX_BYTES, compare_profiles, fingerprint

router = APIRouter(prefix="/api/searches", tags=["images"])
Repository = Annotated[PostgresInvestigationRepository, Depends(get_repository)]
_active_searches: set[UUID] = set()


@router.post("/{search_id}/images", deprecated=True)
async def retired_upload(search_id: UUID):
    raise HTTPException(
        410, "Use POST /image-matches with raw image bytes; uploads are not stored."
    )


@router.post("/{search_id}/image-matches")
async def match_image(search_id: UUID, request: Request, repository: Repository):
    if await repository.get_search(search_id) is None:
        raise HTTPException(404, "search not found")
    if search_id in _active_searches or len(_active_searches) >= 2:
        raise HTTPException(429, "An image check is already running; try again shortly.")
    if request.headers.get("content-type", "").split(";")[0] not in {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/octet-stream",
    }:
        raise HTTPException(415, "Send JPEG, PNG or WebP bytes, not a multipart form.")
    _active_searches.add(search_id)
    data = bytearray()
    try:
        async with asyncio.timeout(20):
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_BYTES:
                    raise HTTPException(413, "Image exceeds 5 MB")
                data.extend(chunk)
        try:
            reference = await asyncio.to_thread(fingerprint, data)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                422, "Invalid image; use a still JPEG, PNG or WebP up to 16 MP."
            ) from exc
        finally:
            data.clear()
        profiles = await repository.list_profile_snapshots_for_search(search_id)
        await repository.session.rollback()
        result = await compare_profiles(reference, profiles)
        return JSONResponse(
            {"search_id": str(search_id), **result},
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    except TimeoutError as exc:
        raise HTTPException(408, "Image upload timed out") from exc
    finally:
        data.clear()
        _active_searches.discard(search_id)
