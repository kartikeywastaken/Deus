"""Bounded public GitHub account search; only returned accounts become candidates."""

import re

import httpx

from .base import BaseConnector
from .schemas import (
    CandidateProfile,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorMode,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class GitHubSearchConnector(BaseConnector):
    name = "github_search"
    version = "github-search-2022-11-28"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.USERNAME, ConnectorInputType.NAME}),
        produced_artifacts=frozenset({ProducedArtifactType.PROFILE}),
        live_supported=True,
    )

    def __init__(self, *, token=None, transport=None):
        super().__init__(ConnectorMode.LIVE)
        self.token = token
        self.transport = transport

    async def discover(self, connector_input):
        username = connector_input.value
        valid = (
            bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username))
            if connector_input.type == ConnectorInputType.USERNAME
            else 1 <= len(username) <= 100 and all(c.isalnum() or c in " -'" for c in username)
        )
        if connector_input.type not in self.accepts or not valid:
            return self._unsupported_input(connector_input)
        query = (
            f"{username} in:login type:user"
            if connector_input.type == ConnectorInputType.USERNAME
            else f'"{username}" in:fullname type:user'
        )
        async with httpx.AsyncClient(
            timeout=10,
            transport=self.transport,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Deus-public-profile-research/0.2",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        ) as client:
            try:
                response = await client.get(
                    "https://api.github.com/search/users",
                    params={"q": query, "per_page": 20, "page": 1},
                )
            except httpx.HTTPError as exc:
                return self._result(ConnectorRunStatus.FAILED, message=type(exc).__name__)
        if response.status_code != 200:
            status = {
                403: ConnectorRunStatus.RATE_LIMITED,
                429: ConnectorRunStatus.RATE_LIMITED,
                401: ConnectorRunStatus.AUTH_REQUIRED,
            }.get(response.status_code, ConnectorRunStatus.FAILED)
            return self._result(
                status, request_count=1, message=f"GitHub user search HTTP {response.status_code}"
            )
        try:
            raw = response.json()
            if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
                raise ValueError("Invalid search response")
            profiles = []
            for item in raw["items"][:20]:
                if item.get("type") != "User":
                    continue
                login = item["login"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login):
                    raise ValueError("Invalid returned login")
                profiles.append(
                    CandidateProfile(
                        platform="github",
                        username=login,
                        platform_account_id=str(item["id"]),
                        canonical_url=f"https://github.com/{login}",
                        avatar_url=item.get("avatar_url"),
                        source_url=str(response.url),
                        discovered_by=[self.name],
                        raw=item,
                    )
                )
        except (ValueError, KeyError, TypeError, AttributeError):
            return self._result(
                ConnectorRunStatus.FAILED,
                request_count=1,
                message="GitHub returned an invalid account-search response.",
            )
        partial = bool(raw.get("incomplete_results") or raw.get("total_count", 0) > 20)
        status = ConnectorRunStatus.SUCCESS if profiles else ConnectorRunStatus.NO_RESULTS
        return self._result(
            ConnectorRunStatus.PARTIAL if partial else status,
            profiles=profiles,
            raw_records=[raw],
            request_count=1,
            metadata={"mode": "live", "candidate_limit": 20},
            message="Only the first 20 search results were collected, or GitHub "
            "reported an incomplete search."
            if partial
            else None,
        )
