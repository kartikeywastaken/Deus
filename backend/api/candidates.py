"""Candidate and evidence read endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.db.repositories import PostgresInvestigationRepository
from backend.investigation.username_questions import relevance_for_profile, user_hint_usernames

from .dependencies import get_repository
from .schemas import CandidateList, CandidateRead, EvidenceList, EvidenceRead

router = APIRouter(prefix="/api/searches", tags=["candidates"])


@router.get("/{search_id}/candidates", response_model=CandidateList)
async def list_candidates(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> CandidateList:
    search = await repository.get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="search not found")
    profiles = await repository.list_profiles_for_search(search_id)
    hinted = user_hint_usernames(await repository.list_questions(search_id))
    relevance = {
        p.id: relevance_for_profile(p.username, search.seeds[0].normalized_value or "", hinted)
        for p in profiles
    }
    profiles.sort(key=lambda p: (relevance[p.id]["priority"], p.platform, p.username or ""))
    hypotheses = await repository.list_hypotheses(search_id)
    membership_by_profile = {}
    for hypothesis in hypotheses:
        for membership in hypothesis.memberships:
            current = membership_by_profile.get(membership.profile_id)
            if current is None or membership.score > current.score:
                membership_by_profile[membership.profile_id] = membership
    return CandidateList(
        items=[
            CandidateRead(
                id=profile.id,
                platform=profile.platform,
                username=profile.username,
                display_name=profile.display_name,
                canonical_url=profile.canonical_url,
                score=(membership.score if membership else None),
                classification=(membership.classification.value if membership else None),
                relevance=relevance[profile.id]["relevance"],
                reason=relevance[profile.id]["reason"],
            )
            for profile in profiles
            if (membership := membership_by_profile.get(profile.id)) is not None or not hypotheses
        ]
    )


@router.get("/{search_id}/evidence", response_model=EvidenceList)
async def list_evidence(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> EvidenceList:
    if await repository.get_search(search_id) is None:
        raise HTTPException(status_code=404, detail="search not found")
    items = await repository.list_evidence(search_id)
    return EvidenceList(
        items=[
            EvidenceRead(
                id=item.id,
                left_profile_id=item.left_profile_id,
                right_profile_id=item.right_profile_id,
                signal_type=item.signal_type,
                direction=item.direction.value,
                normalized_score=item.normalized_score,
                reliability=item.reliability,
                model_contribution=item.model_contribution,
                evidence_family=item.evidence_family,
                explanation=item.explanation,
            )
            for item in items
        ]
    )
