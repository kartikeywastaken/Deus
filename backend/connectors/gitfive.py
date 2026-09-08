"""GitFive's authenticated interactive workflow is not automated."""

from .base import BaseConnector
from .schemas import (
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class GitFiveConnector(BaseConnector):
    name = "gitfive"
    live_status = ConnectorRunStatus.MANUAL
    live_message = (
        "GitFive requires operator login and has usage restrictions. "
        "Unattended integration is not configured."
    )
    documentation_url = "https://github.com/mxrch/GitFive"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.GITHUB_PROFILE}),
        produced_artifacts=frozenset({ProducedArtifactType.OBSERVATION}),
        supports_discovery=False,
        supports_enrichment=True,
        requires_auth=True,
        is_manual=True,
    )

    async def discover(self, connector_input):
        return self._unavailable()
