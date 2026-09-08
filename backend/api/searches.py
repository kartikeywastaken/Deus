"""Search lifecycle endpoints."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.enums import SeedType
from backend.db.repositories import PostgresInvestigationRepository
from backend.investigation.orchestrator import SearchOrchestrator

from .dependencies import get_orchestrator, get_repository
from .schemas import SearchCreate, SearchRead

router = APIRouter(prefix="/api/searches", tags=["searches"])


@router.post("", response_model=SearchRead, status_code=status.HTTP_201_CREATED)
async def create_search(
    payload: SearchCreate,
    orchestrator: Annotated[SearchOrchestrator, Depends(get_orchestrator)],
) -> SearchRead:
    if not orchestrator.settings.mock_connectors:
        if payload.seed_type not in {SeedType.USERNAME, SeedType.PROFILE_URL}:
            raise HTTPException(
                422, "Live searches currently accept usernames or GitHub profile URLs."
            )
        if payload.seed_type is SeedType.PROFILE_URL:
            parsed = urlsplit(payload.value)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "github.com"
                or len(parsed.path.strip("/").split("/")) != 1
            ):
                raise HTTPException(422, "Provide an HTTPS GitHub user profile URL.")
    search = await orchestrator.create_and_run(
        payload.seed_type,
        payload.value,
        scope=payload.scope,
    )
    return SearchRead.model_validate(search)


@router.get("/{search_id}", response_model=SearchRead)
async def get_search(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> SearchRead:
    search = await repository.get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="search not found")
    return SearchRead.model_validate(search)


@router.post("/{search_id}/continue", response_model=SearchRead)
async def continue_search(
    search_id: UUID,
    orchestrator: Annotated[SearchOrchestrator, Depends(get_orchestrator)],
) -> SearchRead:
    try:
        search = await orchestrator.continue_search(search_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SearchRead.model_validate(search)


@router.post("/{search_id}/stop", response_model=SearchRead)
async def stop_search(
    search_id: UUID,
    orchestrator: Annotated[SearchOrchestrator, Depends(get_orchestrator)],
) -> SearchRead:
    try:
        search = await orchestrator.stop_search(search_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SearchRead.model_validate(search)
