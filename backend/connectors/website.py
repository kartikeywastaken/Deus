"""Single-page public link extraction, not an unrestricted crawler."""

from html.parser import HTMLParser
from urllib.parse import urljoin

from .base import BaseConnector
from .safe_http import fetch_public, validate_url
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and len(self.links) < 100:
            self.links.extend(v for k, v in attrs if k == "href" and v)


class WebsiteConnector(BaseConnector):
    name = "website"
    version = "bounded-public-links-v1"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.PROFILE_URL}),
        produced_artifacts=frozenset({ProducedArtifactType.PROFILE}),
        live_supported=True,
    )

    async def discover(self, connector_input):
        if connector_input.type not in self.accepts:
            return self._unsupported_input(connector_input)
        try:
            data, source, _ = await fetch_public(connector_input.value)
            parser = Links()
            parser.feed(data.decode("utf-8", errors="replace"))
            links = []
            for value in parser.links:
                try:
                    link = validate_url(urljoin(source, value))
                    if link not in links:
                        links.append(link)
                except ValueError:
                    continue
            return self._result(
                ConnectorRunStatus.SUCCESS,
                request_count=1,
                profiles=[
                    CandidateProfile(
                        platform="website",
                        canonical_url=source,
                        source_url=source,
                        external_links=links,
                        raw={"observed_links": links, "byte_count": len(data)},
                        discovered_by=[self.name],
                    )
                ],
            )
        except Exception as exc:
            return self._result(
                ConnectorRunStatus.FAILED, request_count=1, message=f"{type(exc).__name__}: {exc}"
            )
