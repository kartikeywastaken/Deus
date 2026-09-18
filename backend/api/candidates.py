"""Candidate and evidence read endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.correlation.engine import candidate_relevance
from backend.db.repositories import PostgresInvestigationRepository
from backend.investigation.account_groups import account_details
from backend.investigation.username_questions import relevance_for_profile, user_hint_usernames

from .dependencies import get_repository
from .schemas import (
    CandidateList,
    CandidateRead,
    EvidenceList,
    EvidenceRead,
    IdentifierList,
    IdentifierRead,
    ObservationList,
    ObservationRead,
)

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
    details = account_details(await repository.list_profile_snapshots_for_search(search_id))
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
                **details[profile.id],
                **candidate_relevance(
                    profile.username,
                    search.seeds[0].normalized_value or "",
                    membership.score if membership else 0.0,
                    seed_type=search.seeds[0].seed_type.value,
                    hinted=hinted,
                ),
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


@router.get("/{search_id}/observations", response_model=ObservationList)
async def list_observations(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> ObservationList:
    if await repository.get_search(search_id) is None:
        raise HTTPException(status_code=404, detail="search not found")
    obs_list = await repository.list_observations_for_search(search_id)
    items = []
    for obs in obs_list:
        raw = obs.raw_data or {}
        extracted = raw.get("extracted_identifiers", [])
        items.append(
            ObservationRead(
                id=obs.id,
                profile_id=obs.profile_id,
                source=obs.source,
                source_url=obs.source_url,
                observation_type=obs.observation_type,
                observed_at=obs.observed_at,
                extracted_identifiers=extracted if isinstance(extracted, list) else [],
            )
        )
    return ObservationList(items=items)


@router.get("/{search_id}/identifiers", response_model=IdentifierList)
async def list_identifiers(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> IdentifierList:
    search = await repository.get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="search not found")
    
    profiles = await repository.list_profiles_for_search(search_id)
    obs_list = await repository.list_observations_for_search(search_id)
    
    # Structure for grouping discovered identifiers by (type, value)
    id_map: dict[tuple[str, str], dict] = {}

    # 1. Add seeds as first-class identifiers
    for seed in search.seeds:
        stype = str(seed.seed_type.value if hasattr(seed.seed_type, "value") else seed.seed_type).upper()
        sval = seed.original_value.strip()
        if sval:
            key = (stype, sval)
            id_map.setdefault(key, {
                "id": f"{stype}:{sval}",
                "value": sval,
                "type": stype,
                "sources": ["seed_input"],
                "linked_profile_ids": set(),
                "observations": [],
            })

    # 2. Add profiles and observations
    for obs in obs_list:
        raw = obs.raw_data or {}
        extracted = raw.get("extracted_identifiers", [])
        obs_item = {
            "source": obs.source,
            "source_url": obs.source_url,
            "observed_at": obs.observed_at.isoformat() if obs.observed_at else None,
            "profile_id": str(obs.profile_id) if obs.profile_id else None,
            "type": obs.observation_type,
        }
        if isinstance(extracted, list):
            for ext in extracted:
                if isinstance(ext, dict) and ext.get("value") and ext.get("type"):
                    itype = str(ext["type"]).upper()
                    ival = str(ext["value"]).strip()
                    if ival:
                        key = (itype, ival)
                        entry = id_map.setdefault(key, {
                            "id": f"{itype}:{ival}",
                            "value": ival,
                            "type": itype,
                            "sources": [],
                            "linked_profile_ids": set(),
                            "observations": [],
                        })
                        if obs.source and obs.source not in entry["sources"]:
                            entry["sources"].append(obs.source)
                        if obs.profile_id:
                            entry["linked_profile_ids"].add(obs.profile_id)
                        entry["observations"].append(obs_item)

    # 3. Add identifiers from profile handles and emails
    for profile in profiles:
        if profile.username:
            key = ("USERNAME", profile.username)
            entry = id_map.setdefault(key, {
                "id": f"USERNAME:{profile.username}",
                "value": profile.username,
                "type": "USERNAME",
                "sources": [],
                "linked_profile_ids": set(),
                "observations": [],
            })
            if profile.platform and profile.platform not in entry["sources"]:
                entry["sources"].append(profile.platform)
            entry["linked_profile_ids"].add(profile.id)
            
        if profile.canonical_url:
            key = ("URL", profile.canonical_url)
            entry = id_map.setdefault(key, {
                "id": f"URL:{profile.canonical_url}",
                "value": profile.canonical_url,
                "type": "URL",
                "sources": [],
                "linked_profile_ids": set(),
                "observations": [],
            })
            if profile.platform and profile.platform not in entry["sources"]:
                entry["sources"].append(profile.platform)
            entry["linked_profile_ids"].add(profile.id)

    # Convert to schema items
    items = []
    for (itype, ival), data in id_map.items():
        sources = data["sources"] or ["observation"]
        items.append(
            IdentifierRead(
                id=data["id"],
                value=data["value"],
                type=data["type"],
                sources=sources,
                independent_source_count=max(1, len(set(sources))),
                linked_profile_ids=list(data["linked_profile_ids"]),
                observations=data["observations"],
            )
        )
    return IdentifierList(items=items)

