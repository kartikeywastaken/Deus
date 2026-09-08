"""Maigret live CLI adapter with explicitly selected offline test fixtures."""

from __future__ import annotations

from typing import Any

from .base import BaseConnector, ConnectorNormalizationError
from .fixtures import discovery_fixture
from .live_cli import discover_live
from .mock_utils import candidate_from_fixture, existence_observation
from .schemas import (
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class MaigretConnector(BaseConnector):
    name = "maigret"
    capabilities = ConnectorCapabilities(
        live_supported=True,
        accepted_inputs=frozenset({ConnectorInputType.USERNAME}),
        produced_artifacts=frozenset(
            {
                ProducedArtifactType.PROFILE,
                ProducedArtifactType.USERNAME,
                ProducedArtifactType.URL,
                ProducedArtifactType.OBSERVATION,
            }
        ),
    )

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            if connector_input.type not in self.accepts:
                return self._unsupported_input(connector_input)
            return await discover_live(self.name, connector_input.value)
        if connector_input.type not in self.capabilities.accepted_inputs:
            return self._unsupported_input(connector_input)
        return self.normalize(discovery_fixture(self.name, connector_input.value))

    def normalize(self, raw: Any) -> ConnectorResult:
        if isinstance(raw, ConnectorResult):
            return raw
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ConnectorNormalizationError(
                "maigret mock payload must be a list of fixture records"
            )

        profiles = [candidate_from_fixture(item, self.name) for item in raw]
        observations = [
            existence_observation(profile, self.name, reliability=0.8) for profile in profiles
        ]
        status = ConnectorRunStatus.SUCCESS if profiles else ConnectorRunStatus.NO_RESULTS
        return self._result(
            status,
            profiles=profiles,
            observations=observations,
            raw_records=raw,
            metadata={"mode": "mock", "fixture_format": "osin_mock_v1"},
        )


MockMaigretConnector = MaigretConnector
