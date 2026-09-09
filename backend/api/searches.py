"""Immediate-return search endpoints backed by durable jobs."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from backend import jobs
from backend.connectors.profile_links import profile_link
from backend.core.config import Settings, get_settings
from backend.core.enums import SeedType
from backend.db.models import UserSearchContext
from backend.db.repositories import PostgresInvestigationRepository

from .dependencies import get_repository
from .schemas import SearchCreate, SearchRead

router = APIRouter(prefix="/api/searches", tags=["searches"])
Repository = Annotated[PostgresInvestigationRepository, Depends(get_repository)]


@router.post("", response_model=SearchRead, status_code=202)
async def create_search(
    payload: SearchCreate,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
):
    if payload.seed_type not in {
        SeedType.USERNAME,
        SeedType.PROFILE_URL,
        SeedType.NAME,
        SeedType.EMAIL,
    }:
        raise HTTPException(422, "Use username, name, or a supported public profile URL.")
    if payload.seed_type == SeedType.EMAIL:
        if (
            payload.scope != "self_audit"
            or not payload.email_self_audit_confirmed
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", payload.value)
        ):
            raise HTTPException(
                422,
                "Email lookups require your own email, self_audit scope and provider consent",
            )
    if payload.seed_type == SeedType.PROFILE_URL:
        if not payload.value.startswith("https://") or not profile_link(payload.value):
            raise HTTPException(422, "Provide a supported HTTPS social account URL, not a post.")
    search = await jobs.create_search(repository, settings, payload)
    return SearchRead.model_validate(search)


@router.get("/{search_id}", response_model=SearchRead)
async def get_search(search_id: UUID, repository: Repository):
    search = await repository.get_search(search_id)
    if search is None:
        raise HTTPException(404, "search not found")
    response = SearchRead.model_validate(search)
    contexts = (
        await repository.session.scalars(
            select(UserSearchContext)
            .where(
                UserSearchContext.search_run_id == search_id,
                UserSearchContext.context_type == "PLANNER_DECISION",
            )
            .order_by(UserSearchContext.created_at.desc())
        )
    ).all()
    advice = [c.value.get("adviser", {}) for c in contexts]
    response.ai_assist = next(
        (a for a in advice if a.get("status") not in {"NOT_NEEDED", "DISABLED"}),
        advice[0] if advice else {},
    )
    return response


@router.post("/{search_id}/continue", response_model=SearchRead, status_code=202)
async def continue_search(search_id: UUID, repository: Repository):
    try:
        return SearchRead.model_validate(await jobs.continue_search(repository, search_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{search_id}/stop", response_model=SearchRead)
async def stop_search(search_id: UUID, repository: Repository):
    try:
        return SearchRead.model_validate(await jobs.stop_search(repository, search_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{search_id}/connector-runs")
async def connector_runs(search_id: UUID, repository: Repository):
    if await repository.get_search(search_id) is None:
        raise HTTPException(404, "search not found")
    runs = await repository.list_connector_runs(search_id)
    return {
        "items": [
            {
                "id": str(r.id),
                "connector": r.connector,
                "status": r.status,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "request_count": r.request_count,
                "error": r.error or r.metadata_json.get("message"),
                "input": r.input_data.get("value"),
                "version": r.connector_version,
            }
            for r in runs
        ]
    }
