"""Connector registration and capability-based eligibility lookup."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .base import Connector
from .gitfive import GitFiveConnector
from .github import GitHubConnector
from .github_search import GitHubSearchConnector
from .maigret import MaigretConnector
from .schemas import ConnectorInputType, ConnectorMode
from .sherlock import SherlockConnector
from .social_analyzer import SocialAnalyzerConnector
from .sylva import SylvaConnector


class DuplicateConnectorError(ValueError):
    pass


class UnknownConnectorError(KeyError):
    pass


class ConnectorRegistry:
    """In-process connector catalogue.

    Selection is based only on declared capabilities.  Execution order and
    loop prevention remain responsibilities of the investigation orchestrator.
    """

    def __init__(self, connectors: Iterable[Connector] = ()) -> None:
        self._connectors: dict[str, Connector] = {}
        for connector in connectors:
            self.register(connector)

    def __iter__(self) -> Iterator[Connector]:
        return iter(self._connectors.values())

    def __len__(self) -> int:
        return len(self._connectors)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._connectors)

    def register(self, connector: Connector) -> None:
        name = connector.name.casefold()
        if name in self._connectors:
            raise DuplicateConnectorError(f"connector {connector.name!r} is registered")
        self._connectors[name] = connector

    def get(self, name: str) -> Connector:
        try:
            return self._connectors[name.casefold()]
        except KeyError as exc:
            raise UnknownConnectorError(name) from exc

    def eligible_for(
        self,
        input_type: ConnectorInputType,
        *,
        discovery_only: bool = False,
        enrichment_only: bool = False,
    ) -> tuple[Connector, ...]:
        if discovery_only and enrichment_only:
            raise ValueError("discovery_only and enrichment_only are mutually exclusive")

        selected: list[Connector] = []
        for connector in self._connectors.values():
            capabilities = connector.capabilities
            if input_type not in capabilities.accepted_inputs:
                continue
            if discovery_only and not capabilities.supports_discovery:
                continue
            if enrichment_only and not capabilities.supports_enrichment:
                continue
            selected.append(connector)
        return tuple(selected)


def build_default_registry(
    *,
    mock_connectors: bool = False,
    github_token: str | None = None,
) -> ConnectorRegistry:
    """Build the MVP connector set in a single explicit runtime mode."""

    mode = ConnectorMode.MOCK if mock_connectors else ConnectorMode.LIVE
    return ConnectorRegistry(
        (
            MaigretConnector(mode),
            SherlockConnector(mode),
            SylvaConnector(mode),
            SocialAnalyzerConnector(mode),
            GitFiveConnector(mode),
            *((GitHubConnector(token=github_token),) if not mock_connectors else ()),
            *((GitHubSearchConnector(token=github_token),) if not mock_connectors else ()),
        )
    )
