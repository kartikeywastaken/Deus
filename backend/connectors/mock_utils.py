"""Shared normalization helpers for Osin-owned fixture records."""

from __future__ import annotations

from typing import Any

from .schemas import CandidateProfile, ObservationArtifact


def candidate_from_fixture(record: dict[str, Any], connector_name: str) -> CandidateProfile:
    """Translate one internal discovery fixture into a normalized candidate."""

    canonical_url = str(record["canonical_url"]).rstrip("/")
    return CandidateProfile(
        platform=str(record["platform"]).casefold(),
        platform_account_id=record.get("platform_account_id"),
        username=record.get("username"),
        display_name=record.get("display_name"),
        canonical_url=canonical_url,
        bio=record.get("bio"),
        location=record.get("location"),
        employer=record.get("employer"),
        external_links=list(record.get("external_links", [])),
        avatar_url=record.get("avatar_url"),
        source_url=canonical_url,
        discovered_by=[connector_name],
        raw={"fixture_id": record.get("fixture_id")},
    )


def existence_observation(
    profile: CandidateProfile,
    connector_name: str,
    reliability: float,
) -> ObservationArtifact:
    """Record profile existence, never identity ownership."""

    return ObservationArtifact(
        signal_type="public_profile_exists",
        value=True,
        reliability=reliability,
        profile_url=profile.canonical_url,
        source_url=profile.source_url,
        raw_data={
            "discovered_by": connector_name,
            "meaning": "candidate profile existence only",
        },
    )
