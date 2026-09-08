"""Social Analyzer public-profile checks with isolated offline fixture support."""

from __future__ import annotations

from typing import Any

from .base import BaseConnector, ConnectorNormalizationError
from .fixtures import profile_fixture, social_analyzer_fixture
from .mock_utils import candidate_from_fixture
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    ObservationArtifact,
    ProducedArtifactType,
)
from .social_live import enrich_live


class SocialAnalyzerConnector(BaseConnector):
    name = "social_analyzer"
    capabilities = ConnectorCapabilities(
        live_supported=True,
        accepted_inputs=frozenset({ConnectorInputType.PROFILE, ConnectorInputType.PROFILE_URL}),
        produced_artifacts=frozenset(
            {
                ProducedArtifactType.PROFILE,
                ProducedArtifactType.PROFILE_OBSERVATION,
                ProducedArtifactType.OBSERVATION,
            }
        ),
        supports_discovery=False,
        supports_enrichment=True,
    )

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            if connector_input.profile is None:
                return self._unsupported_input(connector_input)
            return await self.enrich(connector_input.profile)
        if connector_input.type not in self.capabilities.accepted_inputs:
            return self._unsupported_input(connector_input)
        if connector_input.profile is not None:
            return await self.enrich(connector_input.profile)

        raw = social_analyzer_fixture(connector_input.value)
        if raw is None:
            return self._result(ConnectorRunStatus.NO_RESULTS)
        return self.normalize(raw)

    async def enrich(self, candidate: CandidateProfile) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            return await enrich_live(candidate)
        raw = social_analyzer_fixture(candidate.canonical_url)
        if raw is None:
            return self._result(ConnectorRunStatus.NO_RESULTS)
        return self.normalize(raw)

    def normalize(self, raw: Any) -> ConnectorResult:
        if isinstance(raw, ConnectorResult):
            return raw
        if not isinstance(raw, dict) or "profile_id" not in raw:
            raise ConnectorNormalizationError(
                "social_analyzer mock payload must identify a fixture profile"
            )
        record = profile_fixture(str(raw["profile_id"]))
        if record is None:
            raise ConnectorNormalizationError("unknown social_analyzer fixture profile")

        profile = candidate_from_fixture(record, self.name)
        observations = [
            ObservationArtifact.model_validate(
                {
                    **item,
                    "profile_url": profile.canonical_url,
                    "raw_data": {
                        "fixture_format": "osin_mock_v1",
                        "enriched_by": self.name,
                    },
                }
            )
            for item in raw.get("observations", [])
        ]
        return self._result(
            ConnectorRunStatus.SUCCESS,
            profiles=[profile],
            observations=observations,
            raw_records=[raw],
            metadata={"mode": "mock", "fixture_format": "osin_mock_v1"},
        )


MockSocialAnalyzerConnector = SocialAnalyzerConnector
