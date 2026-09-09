"""High-performance public email service enumeration adapter (Holehe-style passive checks)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class ServiceChecker:
    name: str
    category: str = "social"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        raise NotImplementedError


class SpotifyChecker(ServiceChecker):
    name = "spotify"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://spclient.wg.spotify.com/signup/public/v1/account"
        params = {"validate": "1", "email": email}
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.get(url, params=params, headers=headers, timeout=4.0)
        if res.status_code == 200:
            data = res.json()
            # status == 20 means email is registered
            status = data.get("status")
            if status == 20:
                return {"exists": True, "confidence": 0.95, "canonical_url": "https://spotify.com"}
            if status == 1:
                return {"exists": False}
        return {"exists": None}


class ImgurChecker(ServiceChecker):
    name = "imgur"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://api.imgur.com/account/v1/accounts/email"
        data = {"email": email}
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.post(url, data=data, headers=headers, timeout=4.0)
        if res.status_code == 200:
            data_json = res.json()
            if data_json.get("data", {}).get("available") is False:
                return {"exists": True, "confidence": 0.90, "canonical_url": "https://imgur.com"}
            return {"exists": False}
        return {"exists": None}


class ChessComChecker(ServiceChecker):
    name = "chess.com"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"https://www.chess.com/callback/email/available?email={email}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.get(url, headers=headers, timeout=4.0)
        if res.status_code == 200:
            data = res.json()
            # If available is false, account exists
            if data.get("available") is False:
                return {"exists": True, "confidence": 0.92, "canonical_url": "https://chess.com"}
            return {"exists": False}
        return {"exists": None}


class DuolingoChecker(ServiceChecker):
    name = "duolingo"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"https://www.duolingo.com/2017-06-30/users?email={email}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.get(url, headers=headers, timeout=4.0)
        if res.status_code == 200:
            users = res.json().get("users", [])
            if users:
                u = users[0]
                username = u.get("username")
                name = u.get("name")
                return {
                    "exists": True,
                    "confidence": 0.98,
                    "username": username,
                    "display_name": name,
                    "canonical_url": f"https://duolingo.com/profile/{username}" if username else "https://duolingo.com",
                }
            return {"exists": False}
        return {"exists": None}


class AdobeChecker(ServiceChecker):
    name = "adobe"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://auth.services.adobe.com/signin/v2/users/all"
        data = {"username": email}
        headers = {"User-Agent": "Mozilla/5.0", "X-IMS-CLIENT-ID": "adobedotcom2"}
        res = await client.post(url, json=data, headers=headers, timeout=4.0)
        if res.status_code == 200:
            data_json = res.json()
            # Check if user accounts exist
            if any(item.get("status") == "EXISTS" for item in data_json.get("users", [])):
                return {"exists": True, "confidence": 0.95, "canonical_url": "https://adobe.com"}
            return {"exists": False}
        return {"exists": None}


PUBLIC_CHECKERS = [
    SpotifyChecker(),
    ImgurChecker(),
    ChessComChecker(),
    DuolingoChecker(),
    AdobeChecker(),
]


class HolehePublicAdapter(BaseEmailSource):
    name = "holehe_public"
    category = "enumeration"
    cost = 2
    expected_latency_ms = 800
    reliability = 0.92
    priority = 15

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        client: httpx.AsyncClient = context.get("client") if context else None
        own_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
            own_client = True

        found_services = []
        identifiers = []
        evidence = {}

        try:
            tasks = [checker.check(email, client) for checker in PUBLIC_CHECKERS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for checker, res in zip(PUBLIC_CHECKERS, results, strict=True):
                if isinstance(res, dict) and res.get("exists") is True:
                    found_services.append(checker.name)
                    evidence[checker.name] = res
                    conf = res.get("confidence", 0.85)

                    username = res.get("username")
                    if username:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="username",
                                value=username,
                                normalized_value=username.casefold(),
                                source=f"{self.name}:{checker.name}",
                                confidence=conf,
                                metadata={"platform": checker.name},
                            )
                        )
                    canonical = res.get("canonical_url")
                    if canonical:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="profile_url",
                                value=canonical,
                                normalized_value=canonical.casefold(),
                                source=f"{self.name}:{checker.name}",
                                confidence=conf,
                            )
                        )

            duration = (time.monotonic() - start) * 1000
            if found_services:
                return self._result(
                    EmailSourceStatus.FOUND,
                    account_exists=True,
                    confidence=0.90,
                    identifiers=identifiers,
                    evidence={"found_services": found_services, "details": evidence},
                    response_time_ms=duration,
                    message=f"Registered on: {', '.join(found_services)}",
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
