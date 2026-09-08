"""Sylva public expansion integration status."""

from .base import BaseConnector
from .schemas import (
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class SylvaConnector(BaseConnector):
    name = "sylva"
    live_status = ConnectorRunStatus.MANUAL
    live_message = (
        "Reviewed Sylva 0.1.2: default Handler branches into multiple providers; "
        "its GitHub adapter issues broad commit queries without adequate timeouts. "
        "Use an operator-reviewed configuration manually; automatic execution is not enabled."
    )
    documentation_url = "https://sylva.pfeister.dev/reference/examples/"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.USERNAME, ConnectorInputType.EMAIL}),
        produced_artifacts=frozenset(
            {ProducedArtifactType.IDENTIFIER, ProducedArtifactType.PROFILE}
        ),
        is_manual=True,
    )

    async def discover(self, connector_input):
        return self._unavailable()
