"""Live Social Analyzer public-profile checks."""

from .base import BaseConnector
from .schemas import ConnectorCapabilities, ConnectorInputType, ProducedArtifactType
from .social_live import enrich_live


class SocialAnalyzerConnector(BaseConnector):
    name = "social_analyzer"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.PROFILE}),
        produced_artifacts=frozenset({ProducedArtifactType.OBSERVATION}),
        supports_discovery=False,
        supports_enrichment=True,
        live_supported=True,
    )

    async def discover(self, connector_input):
        if connector_input.profile is None:
            return self._unsupported_input(connector_input)
        return await self.enrich(connector_input.profile)

    async def enrich(self, candidate):
        return await enrich_live(candidate)
