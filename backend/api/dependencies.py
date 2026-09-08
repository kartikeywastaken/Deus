"""FastAPI dependencies that own one database transaction per request."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.db.repositories import PostgresInvestigationRepository
from backend.db.session import get_db_session
from backend.investigation.orchestrator import SearchOrchestrator


async def get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AsyncIterator[PostgresInvestigationRepository]:
    repository = PostgresInvestigationRepository(session)
    try:
        yield repository
    except Exception:
        await session.rollback()
        raise
    else:
        await session.commit()


def get_orchestrator(
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchOrchestrator:
    return SearchOrchestrator(repository, settings)
