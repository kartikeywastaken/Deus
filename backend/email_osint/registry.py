"""Registry for Email OSINT source adapters."""

from __future__ import annotations

from typing import Iterable, Iterator

from .adapters.domain_intel import DomainIntelAdapter
from .adapters.github_email import GitHubEmailAdapter
from .adapters.google_gaia import GoogleGaiaAdapter
from .adapters.gravatar import GravatarAdapter
from .adapters.domain_intel import DomainIntelAdapter
from .adapters.github_email import GitHubEmailAdapter
from .adapters.google_gaia import GoogleGaiaAdapter
from .adapters.gravatar import GravatarAdapter
from .adapters.holehe_public import HolehePublicAdapter
from .base_source import BaseEmailSource


class EmailSourceRegistry:
    """Registry maintaining active Email OSINT source adapters."""

    def __init__(self, sources: Iterable[BaseEmailSource] = ()) -> None:
        self._sources: dict[str, BaseEmailSource] = {}
        for source in sources:
            self.register(source)

    def register(self, source: BaseEmailSource) -> None:
        self._sources[source.name.casefold()] = source

    def get(self, name: str) -> BaseEmailSource:
        return self._sources[name.casefold()]

    def list_sources(self) -> list[BaseEmailSource]:
        return sorted(self._sources.values(), key=lambda s: (s.priority, s.name))

    def __iter__(self) -> Iterator[BaseEmailSource]:
        return iter(self.list_sources())

    def __len__(self) -> int:
        return len(self._sources)


def build_default_email_registry() -> EmailSourceRegistry:
    """Instantiate the default set of email intelligence adapters."""

    return EmailSourceRegistry(
        [
            DomainIntelAdapter(),
            GravatarAdapter(),
            GitHubEmailAdapter(),
            HolehePublicAdapter(),
            GoogleGaiaAdapter(),
        ]
    )
