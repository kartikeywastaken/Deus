"""GitHub Email and commit resolution adapter."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class GitHubEmailAdapter(BaseEmailSource):
    name = "github_email"
    category = "developer"
    cost = 1
    expected_latency_ms = 400
    reliability = 0.98
    priority = 10

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        client: httpx.AsyncClient = context.get("client") if context else None
        own_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=8.0)
            own_client = True

        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Deus-OSINT/1.0"}
        github_token = context.get("github_token") if context else None
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        try:
            # 1. Search GitHub users by email
            url = f"https://api.github.com/search/users?q={email}+in:email"
            res = await client.get(url, headers=headers)
            duration = (time.monotonic() - start) * 1000

            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if items:
                    first = items[0]
                    username = first.get("login")
                    canonical_url = first.get("html_url") or f"https://github.com/{username}"
                    avatar_url = first.get("avatar_url")

                    identifiers = [
                        DiscoveredIdentifier(
                            type="username",
                            value=username,
                            normalized_value=username.casefold(),
                            source=self.name,
                            confidence=0.98,
                            metadata={"platform": "github"},
                        ),
                        DiscoveredIdentifier(
                            type="profile_url",
                            value=canonical_url,
                            normalized_value=canonical_url.casefold(),
                            source=self.name,
                            confidence=0.98,
                        ),
                    ]

                    # Fetch user profile to extract display_name, bio, blog
                    user_res = await client.get(f"https://api.github.com/users/{username}", headers=headers)
                    display_name = None
                    if user_res.status_code == 200:
                        u_data = user_res.json()
                        display_name = u_data.get("name")
                        if display_name:
                            identifiers.append(
                                DiscoveredIdentifier(
                                    type="display_name",
                                    value=display_name,
                                    normalized_value=display_name.casefold(),
                                    source=self.name,
                                    confidence=0.95,
                                )
                            )
                        blog = u_data.get("blog")
                        if blog:
                            blog_url = blog if blog.startswith("http") else f"https://{blog}"
                            identifiers.append(
                                DiscoveredIdentifier(
                                    type="profile_url",
                                    value=blog_url,
                                    normalized_value=blog_url.casefold(),
                                    source=self.name,
                                    confidence=0.90,
                                )
                            )

                    return self._result(
                        EmailSourceStatus.FOUND,
                        account_exists=True,
                        canonical_url=canonical_url,
                        username=username,
                        display_name=display_name,
                        avatar_url=avatar_url,
                        confidence=0.98,
                        identifiers=identifiers,
                        evidence={"search_item": first},
                        response_time_ms=duration,
                    )

            # 2. Fallback search commit author email
            commit_url = f"https://api.github.com/search/commits?q=author-email:{email}"
            commit_headers = {**headers, "Accept": "application/vnd.github.cloak-preview+json"}
            commit_res = await client.get(commit_url, headers=commit_headers)
            if commit_res.status_code == 200:
                c_data = commit_res.json()
                c_items = c_data.get("items", [])
                if c_items:
                    author = c_items[0].get("author") or {}
                    username = author.get("login")
                    commit_info = c_items[0].get("commit", {}).get("author", {})
                    display_name = commit_info.get("name")

                    identifiers = []
                    canonical_url = None
                    if username:
                        canonical_url = f"https://github.com/{username}"
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="username",
                                value=username,
                                normalized_value=username.casefold(),
                                source=self.name,
                                confidence=0.95,
                                metadata={"platform": "github"},
                            )
                        )
                    if display_name:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="display_name",
                                value=display_name,
                                normalized_value=display_name.casefold(),
                                source=self.name,
                                confidence=0.88,
                            )
                        )

                    if identifiers:
                        return self._result(
                            EmailSourceStatus.FOUND,
                            account_exists=True,
                            canonical_url=canonical_url,
                            username=username,
                            display_name=display_name,
                            confidence=0.90,
                            identifiers=identifiers,
                            evidence={"commit_author": commit_info},
                            response_time_ms=(time.monotonic() - start) * 1000,
                        )

            return self._result(EmailSourceStatus.NOT_FOUND, response_time_ms=duration)
        except Exception as exc:
            return self._result(
                EmailSourceStatus.ERROR,
                message=str(exc),
                response_time_ms=(time.monotonic() - start) * 1000,
            )
        finally:
            if own_client:
                await client.aclose()
