"""Gravatar profile and identity discovery adapter."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class GravatarAdapter(BaseEmailSource):
    name = "gravatar"
    category = "social"
    cost = 1
    expected_latency_ms = 300
    reliability = 0.95
    priority = 10

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        client: httpx.AsyncClient = context.get("client") if context else None
        own_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0, follow_redirects=True)
            own_client = True

        try:
            normalized = email.strip().lower()
            sha256_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            url = f"https://en.gravatar.com/{sha256_hash}.json"

            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            res = await client.get(url, headers=headers)
            duration = (time.monotonic() - start) * 1000

            if res.status_code == 404:
                # Avatar image check fallback
                img_url = f"https://www.gravatar.com/avatar/{sha256_hash}?d=404"
                img_res = await client.head(img_url, headers=headers)
                if img_res.status_code == 200:
                    return self._result(
                        EmailSourceStatus.FOUND,
                        account_exists=True,
                        avatar_url=f"https://www.gravatar.com/avatar/{sha256_hash}",
                        canonical_url=f"https://gravatar.com/{sha256_hash}",
                        confidence=0.9,
                        response_time_ms=duration,
                        message="Gravatar avatar photo observed.",
                    )
                return self._result(EmailSourceStatus.NOT_FOUND, response_time_ms=duration)

            if res.status_code == 200:
                data = res.json()
                entry = data.get("entry", [{}])[0]
                display_name = entry.get("displayName") or entry.get("preferredUsername")
                preferred_username = entry.get("preferredUsername")
                profile_url = entry.get("profileUrl") or f"https://gravatar.com/{sha256_hash}"
                avatar_url = entry.get("thumbnailUrl") or f"https://www.gravatar.com/avatar/{sha256_hash}"

                identifiers: list[DiscoveredIdentifier] = []
                if preferred_username:
                    identifiers.append(
                        DiscoveredIdentifier(
                            type="username",
                            value=preferred_username,
                            normalized_value=preferred_username.casefold(),
                            source=self.name,
                            confidence=0.92,
                            metadata={"platform": "gravatar"},
                        )
                    )
                if display_name:
                    identifiers.append(
                        DiscoveredIdentifier(
                            type="display_name",
                            value=display_name,
                            normalized_value=display_name.casefold(),
                            source=self.name,
                            confidence=0.85,
                        )
                    )

                # Extract connected profile links
                urls = entry.get("urls", [])
                for u in urls:
                    link_val = u.get("value")
                    if link_val:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="profile_url",
                                value=link_val,
                                normalized_value=link_val.casefold(),
                                source=self.name,
                                confidence=0.88,
                            )
                        )

                return self._result(
                    EmailSourceStatus.FOUND,
                    account_exists=True,
                    canonical_url=profile_url,
                    display_name=display_name,
                    username=preferred_username,
                    avatar_url=avatar_url,
                    confidence=0.95,
                    identifiers=identifiers,
                    evidence={"entry": entry},
                    response_time_ms=duration,
                )

            if res.status_code == 429:
                return self._result(EmailSourceStatus.RATE_LIMITED, response_time_ms=duration)

            return self._result(
                EmailSourceStatus.ERROR,
                message=f"HTTP {res.status_code}",
                response_time_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return self._result(
                EmailSourceStatus.ERROR, message=str(exc), response_time_ms=duration
            )
        finally:
            if own_client:
                await client.aclose()
