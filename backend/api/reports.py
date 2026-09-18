"""Report projection endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.db.repositories import PostgresInvestigationRepository

from .dependencies import get_repository
from .schemas import ReportEnvelope

router = APIRouter(prefix="/api/searches", tags=["reports"])


@router.get("/{search_id}/report", response_model=ReportEnvelope)
async def get_report(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> ReportEnvelope:
    if await repository.get_search(search_id) is None:
        raise HTTPException(status_code=404, detail="search not found")
    report = await repository.get_latest_report(search_id)
    return ReportEnvelope(report_data=report.report_data if report else None)
