"""Public GitHub REST API adapter; no credentials required for public users."""

import re
from urllib.parse import urlsplit

import httpx

from .base import BaseConnector
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    ObservationArtifact,
    ProducedArtifactType,
)


class GitHubConnector(BaseConnector):
    name = "github"
    version = "github-rest-2022-11-28"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.USERNAME, ConnectorInputType.PROFILE_URL}),
        produced_artifacts=frozenset(
            {ProducedArtifactType.PROFILE, ProducedArtifactType.OBSERVATION}
        ),
        live_supported=True,
    )

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, *, token: str | None = None
    ) -> None:
        super().__init__(ConnectorMode.LIVE)
        self.transport = transport
        self.token = token

    async def discover(self, connector_input: ConnectorInput) -> ConnectorResult:
        username = connector_input.value
        if connector_input.type is ConnectorInputType.PROFILE_URL:
            parsed = urlsplit(username)
            if parsed.scheme != "https" or parsed.hostname != "github.com":
                return self._unsupported_input(connector_input)
            username = parsed.path.strip("/")
        elif connector_input.type is not ConnectorInputType.USERNAME:
            return self._unsupported_input(connector_input)
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", username):
            return self._result(ConnectorRunStatus.NO_RESULTS, message="Invalid GitHub username.")
        social_response = None
        social_error = None
        requests = 1
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=10,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Deus-public-profile-research/0.1",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        ) as client:
            try:
                response = await client.get(f"https://api.github.com/users/{username}")
            except httpx.HTTPError as exc:
                return self._result(ConnectorRunStatus.FAILED, message=type(exc).__name__)
            if response.status_code == 200:
                requests += 1
                try:
                    social_response = await client.get(
                        f"https://api.github.com/users/{username}/social_accounts",
                        params={"per_page": 100},
                    )
                    if social_response.status_code != 200:
                        social_error = f"Social links: GitHub HTTP {social_response.status_code}"
                except httpx.HTTPError as exc:
                    social_error = f"Social links: {type(exc).__name__}"
        statuses = {
            404: ConnectorRunStatus.NO_RESULTS,
            401: ConnectorRunStatus.AUTH_REQUIRED,
            403: ConnectorRunStatus.RATE_LIMITED,
            429: ConnectorRunStatus.RATE_LIMITED,
        }
        if response.status_code != 200:
            return self._result(
                statuses.get(response.status_code, ConnectorRunStatus.FAILED),
                request_count=1,
                message=f"GitHub HTTP {response.status_code}",
            )
        try:
            raw = response.json()
            if not isinstance(raw, dict) or not {"type", "id", "login", "html_url"} <= raw.keys():
                raise ValueError("Invalid user payload")
        except ValueError:
            return self._result(
                ConnectorRunStatus.FAILED,
                request_count=requests,
                message="GitHub returned an invalid user payload.",
            )
        if raw.get("type") != "User":
            return self._result(
                ConnectorRunStatus.NO_RESULTS,
                request_count=1,
                message="The GitHub account is not an individual user.",
            )
        links = []
        if raw.get("blog"):
            blog = raw["blog"]
            links.append(blog if "://" in blog else f"https://{blog}")
        profile = CandidateProfile(
            platform="github",
            platform_account_id=str(raw["id"]),
            canonical_url=raw["html_url"],
            username=raw["login"],
            display_name=raw.get("name"),
            bio=raw.get("bio"),
            location=raw.get("location"),
            employer=raw.get("company"),
            avatar_url=raw.get("avatar_url"),
            external_links=links,
            source_url=str(response.url),
            discovered_by=[self.name],
            raw=raw,
        )
        observations = []
        records = [raw]
        if social_response is not None and social_response.status_code == 200:
            try:
                social = social_response.json()
                if not isinstance(social, list):
                    raise ValueError("Invalid links payload")
                for item in social:
                    if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                        raise ValueError("Invalid link")
                    if item["url"].startswith("https://"):
                        observations.append(
                            ObservationArtifact(
                                signal_type="PUBLIC_EXTERNAL_LINK",
                                value=item["url"],
                                reliability=0.95,
                                profile_url=profile.canonical_url,
                                source_url=str(social_response.url),
                                raw_data=item,
                            )
                        )
                records.append({"social_accounts": social, "source_url": str(social_response.url)})
                if 'rel="next"' in social_response.headers.get("link", ""):
                    social_error = "Social-account pagination limit reached."
            except (ValueError, TypeError):
                social_error = "GitHub returned an invalid social-account payload."
        return self._result(
            ConnectorRunStatus.PARTIAL if social_error else ConnectorRunStatus.SUCCESS,
            profiles=[profile],
            observations=observations,
            raw_records=records,
            request_count=requests,
            message=social_error,
            metadata={"mode": "live"},
        )
