"""Single-page public link extraction, not an unrestricted crawler."""

from html.parser import HTMLParser
from urllib.parse import urljoin

from .base import BaseConnector
from .profile_links import profile_link
from .safe_http import fetch_public, validate_url
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ObservationArtifact,
    ProducedArtifactType,
)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.identity_links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and len(self.links) < 100:
            self.links.extend(v for k, v in attrs if k == "href" and v)
            values = dict(attrs)
            if "me" in (values.get("rel") or "").split():
                self.identity_links.extend(v for k, v in attrs if k == "href" and v)


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
            # rel=me is an explicit identity assertion. Ordinary anchors may be
            # navigation, friends or dependencies and must not merge identities.
            for value in parser.identity_links:
                try:
                    link = validate_url(urljoin(source, value))
                    if link not in links:
                        links.append(link)
                except ValueError:
                    continue
            identity = profile_link(source)
            references = []
            for value in parser.links:
                target = profile_link(urljoin(source, value))
                if target and target[2] not in links:
                    references.append(
                        ObservationArtifact(
                            signal_type="PAGE_SOCIAL_REFERENCE",
                            value=target[2],
                            reliability=0.5,
                            profile_url=source,
                            source_url=source,
                            raw_data={
                                "identity_evidence": False,
                                "attribution": "UNVERIFIED_REFERENCE",
                            },
                        )
                    )
            if profile_link(connector_input.value) and not identity:
                return self._result(
                    ConnectorRunStatus.PARTIAL,
                    request_count=1,
                    message="Profile redirected away from an account page; context unverified.",
                )
            return self._result(
                ConnectorRunStatus.SUCCESS if links else ConnectorRunStatus.PARTIAL,
                message=None
                if links
                else "Public page has no extractable rel=me identity links. "
                "It may be restricted or require JavaScript; no absence conclusion.",
                request_count=1,
                observations=references,
                profiles=[
                    CandidateProfile(
                        platform=identity[0] if identity else "website",
                        username=identity[1] if identity else None,
                        canonical_url=source,
                        source_url=source,
                        external_links=links,
                        raw={
                            "observed_links": links,
                            "byte_count": len(data),
                            "unattributed_links": parser.links[:100],
                        },
                        discovered_by=[self.name],
                    )
                ],
            )
        except Exception as exc:
            return self._result(
                ConnectorRunStatus.FAILED, request_count=1, message=f"{type(exc).__name__}: {exc}"
            )
