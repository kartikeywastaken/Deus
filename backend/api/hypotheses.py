"""Ranked identity-hypothesis endpoint."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.db.repositories import PostgresInvestigationRepository

from .dependencies import get_repository
from .schemas import HypothesisList, HypothesisRead, MembershipRead

router = APIRouter(prefix="/api/searches", tags=["hypotheses"])


@router.get("/{search_id}/hypotheses", response_model=HypothesisList)
async def list_hypotheses(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> HypothesisList:
    if await repository.get_search(search_id) is None:
        raise HTTPException(status_code=404, detail="search not found")
    hypotheses = await repository.list_hypotheses(search_id)
    return HypothesisList(
        items=[
            HypothesisRead(
                id=item.id,
                rank=item.rank,
                overall_score=item.overall_score,
                classification=item.classification.value,
                memberships=[
                    MembershipRead(
                        profile_id=membership.profile_id,
                        score=membership.score,
                        classification=membership.classification.value,
                        support_count=membership.support_count,
                        contradiction_count=membership.contradiction_count,
                    )
                    for membership in item.memberships
                ],
            )
            for item in hypotheses
        ]
    )
