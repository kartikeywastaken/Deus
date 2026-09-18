"""Username OSINT Engine – aggregates intelligence from discovered profiles.

Unlike email OSINT which has dedicated tools (holehe, ghunt), username OSINT
leverages the existing connector infrastructure (maigret, sherlock, github)
and aggregates their results into a unified intelligence report.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from backend.connectors import (
    ConnectorInput,
    ConnectorInputType,
    ConnectorResult,
    ConnectorRunStatus,
    build_default_registry,
)

from .schemas import (
    UsernameOSINTResult,
    UsernameSourceResult,
    UsernameSourceStatus,
)

logger = logging.getLogger(__name__)

# Platform category classification
PLATFORM_CATEGORIES: dict[str, str] = {
    "github": "developer",
    "githubgist": "developer",
    "gitlab": "developer",
    "bitbucket": "developer",
    "stackoverflow": "developer",
    "hackernoon": "developer",
    "dev.to": "developer",
    "codepen": "developer",
    "npm": "developer",
    "pypi": "developer",
    "twitter": "social",
    "x": "social",
    "instagram": "social",
    "facebook": "social",
    "mastodon": "social",
    "bluesky": "social",
    "threads": "social",
    "tiktok": "social",
    "snapchat": "social",
    "reddit": "social",
    "tumblr": "social",
    "pinterest": "media",
    "flickr": "media",
    "youtube": "media",
    "vimeo": "media",
    "soundcloud": "media",
    "spotify": "media",
    "bandcamp": "media",
    "twitch": "gaming",
    "steam": "gaming",
    "xbox": "gaming",
    "playstation": "gaming",
    "roblox": "gaming",
    "minecraft": "gaming",
    "linkedin": "professional",
    "indeed": "professional",
    "angellist": "professional",
    "crunchbase": "professional",
    "medium": "blogging",
    "wordpress": "blogging",
    "blogger": "blogging",
    "substack": "blogging",
    "telegram": "messaging",
    "discord": "messaging",
    "signal": "messaging",
    "keybase": "security",
    "hackthebox": "security",
    "tryhackme": "security",
}


def _classify_platform(platform: str) -> str:
    """Classify a platform into a category."""
    key = platform.lower().replace(" ", "").replace(".", "")
    for pattern, category in PLATFORM_CATEGORIES.items():
        if pattern in key or key in pattern:
            return category
    return "other"


class UsernameOSINTEngine:
    """Orchestrates username discovery across multiple connectors and aggregates intelligence."""

    def __init__(self, *, github_token: str | None = None) -> None:
        self._github_token = github_token

    async def discover(
        self,
        username: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> UsernameOSINTResult:
        """Run complete username intelligence flow."""

        start_time = time.monotonic()
        normalized = username.strip().lstrip("@")

        if not re.fullmatch(r"[\w][\w.-]{0,63}", normalized):
            return UsernameOSINTResult(
                username=username,
                normalized_username=normalized,
            )

        github_token = (context or {}).get("github_token") or self._github_token
        registry = build_default_registry(github_token=github_token)

        # Collect connectors that accept USERNAME input
        username_connectors = [
            c for c in registry
            if ConnectorInputType.USERNAME in c.capabilities.accepted_inputs
            and c.capabilities.supports_discovery
        ]

        connector_input = ConnectorInput(
            type=ConnectorInputType.USERNAME,
            value=normalized,
        )

        # Run all connectors concurrently
        tasks = [
            self._run_connector(connector, connector_input)
            for connector in username_connectors
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        source_results: list[UsernameSourceResult] = []
        display_names: list[str] = []
        emails: list[str] = []
        locations: list[str] = []
        bios: list[str] = []
        avatar_urls: list[str] = []
        category_counts: dict[str, int] = {}

        for result in raw_results:
            if isinstance(result, Exception):
                logger.error("Username connector error: %s", result)
                continue
            if not isinstance(result, list):
                continue

            for sr in result:
                source_results.append(sr)
                if sr.account_exists:
                    cat = _classify_platform(sr.platform)
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                    if sr.display_name and sr.display_name not in display_names:
                        display_names.append(sr.display_name)
                    if sr.email and sr.email not in emails:
                        emails.append(sr.email)
                    if sr.location and sr.location not in locations:
                        locations.append(sr.location)
                    if sr.bio and sr.bio not in bios:
                        bios.append(sr.bio)
                    if sr.avatar_url and sr.avatar_url not in avatar_urls:
                        avatar_urls.append(sr.avatar_url)

        accounts_found = sum(1 for sr in source_results if sr.account_exists)
        sources_checked = len(source_results)

        # Calculate confidence based on coverage and matches
        if accounts_found >= 5:
            confidence = 0.95
        elif accounts_found >= 3:
            confidence = 0.85
        elif accounts_found >= 1:
            confidence = 0.70
        else:
            confidence = 0.30

        duration_ms = (time.monotonic() - start_time) * 1000

        return UsernameOSINTResult(
            username=username,
            normalized_username=normalized,
            sources_checked=sources_checked,
            accounts_found=accounts_found,
            source_results=source_results,
            overall_confidence=confidence,
            scan_duration_ms=duration_ms,
            display_names_found=display_names[:10],
            emails_found=emails[:10],
            locations_found=locations[:5],
            bios_found=bios[:5],
            avatar_urls=avatar_urls[:10],
            platform_categories=category_counts,
        )

    async def _run_connector(
        self,
        connector,
        connector_input: ConnectorInput,
    ) -> list[UsernameSourceResult]:
        """Run a single connector and convert its results to UsernameSourceResult."""

        results: list[UsernameSourceResult] = []
        start = time.monotonic()

        try:
            result: ConnectorResult = await asyncio.wait_for(
                connector.discover(connector_input),
                timeout=120,
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            if result.status == ConnectorRunStatus.SUCCESS and result.profiles:
                for profile in result.profiles:
                    platform = getattr(profile, "platform", connector.name) or connector.name
                    results.append(
                        UsernameSourceResult(
                            source_name=connector.name,
                            platform=platform,
                            category=_classify_platform(platform),
                            status=UsernameSourceStatus.FOUND,
                            account_exists=True,
                            canonical_url=getattr(profile, "canonical_url", None),
                            display_name=getattr(profile, "display_name", None),
                            username=getattr(profile, "username", None) or connector_input.value,
                            avatar_url=getattr(profile, "avatar_url", None),
                            bio=getattr(profile, "bio", None),
                            location=getattr(profile, "location", None),
                            email=getattr(profile, "email", None),
                            confidence=0.85,
                            evidence=getattr(profile, "raw", None) or {},
                            response_time_ms=elapsed_ms,
                        )
                    )
            elif result.status in {ConnectorRunStatus.FAILED, ConnectorRunStatus.UNAVAILABLE}:
                results.append(
                    UsernameSourceResult(
                        source_name=connector.name,
                        platform=connector.name,
                        category="other",
                        status=UsernameSourceStatus.ERROR,
                        message=result.message,
                        response_time_ms=elapsed_ms,
                    )
                )
            else:
                results.append(
                    UsernameSourceResult(
                        source_name=connector.name,
                        platform=connector.name,
                        category="other",
                        status=UsernameSourceStatus.NOT_FOUND,
                        response_time_ms=elapsed_ms,
                    )
                )

        except asyncio.TimeoutError:
            results.append(
                UsernameSourceResult(
                    source_name=connector.name,
                    platform=connector.name,
                    category="other",
                    status=UsernameSourceStatus.TIMEOUT,
                    message=f"{connector.name} timed out",
                    response_time_ms=(time.monotonic() - start) * 1000,
                )
            )
        except Exception as exc:
            logger.exception("Connector %s failed", connector.name)
            results.append(
                UsernameSourceResult(
                    source_name=connector.name,
                    platform=connector.name,
                    category="other",
                    status=UsernameSourceStatus.ERROR,
                    message=str(exc),
                    response_time_ms=(time.monotonic() - start) * 1000,
                )
            )

        return results
