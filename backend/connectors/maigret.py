"""Live Maigret adapter."""

from .base import BaseConnector
from .live_cli import discover_live
from .schemas import ConnectorCapabilities, ConnectorInputType, ProducedArtifactType


class MaigretConnector(BaseConnector):
    name = "maigret"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.USERNAME}),
        produced_artifacts=frozenset({ProducedArtifactType.PROFILE}),
        live_supported=True,
    )

    async def discover(self, connector_input):
        if connector_input.type not in self.accepts:
            return self._unsupported_input(connector_input)
        return await discover_live(self.name, connector_input.value)
