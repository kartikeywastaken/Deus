"""Common connector contract.

Live integrations return explicit terminal statuses and never fall back to fixtures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol, runtime_checkable

from .schemas import (
    CandidateProfile,
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class ConnectorNormalizationError(ValueError):
    """Raised when an adapter receives a payload it does not understand."""


@runtime_checkable
class Connector(Protocol):
    """Structural type consumed by the registry and orchestrator."""

    name: str
    version: str
    capabilities: ConnectorCapabilities
    mode: ConnectorMode

    @property
    def availability(self) -> ConnectorAvailability: ...

    @property
    def accepts(self) -> frozenset[ConnectorInputType]: ...

    @property
    def produces(self) -> frozenset[ProducedArtifactType]: ...

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult: ...

    async def enrich(self, candidate: CandidateProfile) -> ConnectorResult: ...

    def normalize(self, raw: Any) -> ConnectorResult: ...


class BaseConnector(ABC):
    """Small base class shared by deterministic adapter implementations."""

    name: str
    version = "live-adapter-v1"
    capabilities: ConnectorCapabilities
    live_status = ConnectorRunStatus.DISABLED
    live_message = "This live connector is not implemented. No collection was performed."

    def __init__(self, mode: ConnectorMode | str = ConnectorMode.LIVE) -> None:
        self.mode = ConnectorMode(mode)

    @property
    def availability(self) -> ConnectorAvailability:
        packages = {
            "maigret": "maigret",
            "sherlock": "sherlock-project",
            "social_analyzer": "social-analyzer",
        }
        if self.mode is ConnectorMode.LIVE and self.name in packages:
            try:
                version(packages[self.name])
            except PackageNotFoundError:
                return ConnectorAvailability.UNAVAILABLE
        if self.capabilities.live_supported:
            return ConnectorAvailability.AVAILABLE
        if self.live_status is ConnectorRunStatus.UNAVAILABLE:
            return ConnectorAvailability.UNAVAILABLE
        return ConnectorAvailability(self.live_status.value)

    @property
    def accepts(self) -> frozenset[ConnectorInputType]:
        """Compatibility shorthand for capability-driven orchestrators."""

        return self.capabilities.accepted_inputs

    @property
    def produces(self) -> frozenset[ProducedArtifactType]:
        """Compatibility shorthand for capability-driven pivot planning."""

        return self.capabilities.produced_artifacts

    @abstractmethod
    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        """Discover or expand candidates from a typed seed/pivot."""

    async def enrich(self, candidate: CandidateProfile) -> ConnectorResult:
        """Default enrichment behavior for discovery-only connectors."""

        return self._result(
            ConnectorRunStatus.NO_RESULTS,
            message=f"{self.name} does not provide profile enrichment.",
        )

    def normalize(self, raw: Any) -> ConnectorResult:
        """Accept an already normalized result; concrete adapters parse fixtures."""

        if isinstance(raw, ConnectorResult):
            return raw
        raise ConnectorNormalizationError(
            f"{self.name} cannot normalize payload type {type(raw).__name__}"
        )

    async def healthcheck(self) -> dict:
        return {
            "name": self.name,
            "status": self.availability.value,
            "version": self.version,
            "reason": None
            if self.availability == ConnectorAvailability.AVAILABLE
            else self.live_message,
            "documentation_url": getattr(self, "documentation_url", None),
            "capabilities": self.capabilities.model_dump(mode="json"),
        }

    def _unavailable(self) -> ConnectorResult:
        return self._result(self.live_status, message=self.live_message)

    def _unsupported_input(self, connector_input: ConnectorInput) -> ConnectorResult:
        return self._result(
            ConnectorRunStatus.NO_RESULTS,
            message=(f"{self.name} does not accept input type {connector_input.type.value}."),
        )

    def _result(
        self,
        status: ConnectorRunStatus,
        **values: Any,
    ) -> ConnectorResult:
        return ConnectorResult(
            connector=self.name,
            connector_version=self.version,
            status=status,
            **values,
        )
