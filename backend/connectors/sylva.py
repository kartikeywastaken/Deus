"""Sylva expansion adapter backed only by deterministic fixtures."""

from __future__ import annotations

from typing import Any

from .base import BaseConnector, ConnectorNormalizationError
from .fixtures import sylva_fixture
from .schemas import (
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    IdentifierArtifact,
    ProducedArtifactType,
    RelationshipArtifact,
)


class SylvaConnector(BaseConnector):
    name = "sylva"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.USERNAME, ConnectorInputType.EMAIL}),
        produced_artifacts=frozenset(
            {
                ProducedArtifactType.PROFILE,
                ProducedArtifactType.USERNAME,
                ProducedArtifactType.IDENTIFIER,
                ProducedArtifactType.RELATIONSHIP,
            }
        ),
    )
    live_status = ConnectorRunStatus.UNAVAILABLE
    live_message = (
        "Live Sylva automation is unavailable in this version; only the "
        "documented mock adapter is enabled."
    )

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        if self.mode is ConnectorMode.LIVE:
            return self._live_placeholder()
        if connector_input.type not in self.capabilities.accepted_inputs:
            return self._unsupported_input(connector_input)
        raw = sylva_fixture(connector_input.value)
        if raw is None:
            return self._result(
                ConnectorRunStatus.NO_RESULTS,
                metadata={"mode": "mock", "fixture_format": "osin_mock_v1"},
            )
        return self.normalize(raw)

    def normalize(self, raw: Any) -> ConnectorResult:
        if isinstance(raw, ConnectorResult):
            return raw
        if not isinstance(raw, dict):
            raise ConnectorNormalizationError("sylva mock payload must be a fixture mapping")
        identifiers = [
            IdentifierArtifact.model_validate(item) for item in raw.get("identifiers", [])
        ]
        relationships = [
            RelationshipArtifact.model_validate(item) for item in raw.get("relationships", [])
        ]
        has_results = bool(identifiers or relationships)
        return self._result(
            ConnectorRunStatus.SUCCESS if has_results else ConnectorRunStatus.NO_RESULTS,
            identifiers=identifiers,
            relationships=relationships,
            raw_records=[raw],
            metadata={"mode": "mock", "fixture_format": "osin_mock_v1"},
        )


MockSylvaConnector = SylvaConnector
