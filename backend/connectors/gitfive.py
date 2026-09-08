"""GitFive enrichment adapter with no executable live integration yet."""

from __future__ import annotations

from typing import Any

from .base import BaseConnector, ConnectorNormalizationError
from .fixtures import gitfive_fixture
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    IdentifierArtifact,
    ObservationArtifact,
    ProducedArtifactType,
)


class GitFiveConnector(BaseConnector):
    name = "gitfive"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.GITHUB_PROFILE}),
        produced_artifacts=frozenset(
            {
                ProducedArtifactType.OBSERVATION,
                ProducedArtifactType.EMAIL_IDENTIFIER,
                ProducedArtifactType.USERNAME_HISTORY,
                ProducedArtifactType.REPOSITORY,
            }
        ),
        supports_discovery=False,
        supports_enrichment=True,
    )
    live_status = ConnectorRunStatus.UNAVAILABLE
    live_message = (
        "GitFive is not integrated: it requires interactive GitHub login "
        "and a usage-policy review. "
        "The separate GitHub REST connector collects public profile data without GitFive."
    )

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            return self._live_placeholder()
        if connector_input.type not in self.capabilities.accepted_inputs:
            return self._unsupported_input(connector_input)
        if connector_input.profile is None:
            return self._result(
                ConnectorRunStatus.NO_RESULTS,
                message="GitFive requires a normalized GitHub candidate profile.",
            )
        return await self.enrich(connector_input.profile)

    async def enrich(self, candidate: CandidateProfile) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            return self._live_placeholder()
        if candidate.platform.casefold() != "github":
            return self._result(
                ConnectorRunStatus.NO_RESULTS,
                message="GitFive is eligible only for GitHub profiles.",
            )
        raw = gitfive_fixture(candidate.canonical_url)
        if raw is None:
            return self._result(ConnectorRunStatus.NO_RESULTS)
        return self.normalize(raw)

    def normalize(self, raw: Any) -> ConnectorResult:
        if isinstance(raw, ConnectorResult):
            return raw
        if not isinstance(raw, dict):
            raise ConnectorNormalizationError("gitfive mock payload must be a fixture mapping")
        identifiers = [
            IdentifierArtifact.model_validate(item) for item in raw.get("identifiers", [])
        ]
        observations = [
            ObservationArtifact.model_validate(
                {
                    **item,
                    "profile_url": item.get("profile_url") or item.get("source_url"),
                    "raw_data": {
                        "fixture_format": "osin_mock_v1",
                        "enriched_by": self.name,
                    },
                }
            )
            for item in raw.get("observations", [])
        ]
        has_results = bool(identifiers or observations)
        return self._result(
            ConnectorRunStatus.SUCCESS if has_results else ConnectorRunStatus.NO_RESULTS,
            identifiers=identifiers,
            observations=observations,
            raw_records=[raw],
            metadata={"mode": "mock", "fixture_format": "osin_mock_v1"},
        )


MockGitFiveConnector = GitFiveConnector
