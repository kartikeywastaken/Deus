"""Google GAIA ID and account detection adapter (passive metadata & GHunt integration)."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class GoogleGaiaAdapter(BaseEmailSource):
    name = "google_gaia"
    category = "google"
    cost = 2
    expected_latency_ms = 500
    reliability = 0.90
    priority = 20

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        
        # 1. GHunt integration if enabled and configured
        ghunt_conn = context.get("ghunt_connector") if context else None
        if ghunt_conn:
            try:
                from backend.connectors.schemas import ConnectorInput, ConnectorInputType
                res = await ghunt_conn.discover(
                    ConnectorInput(type=ConnectorInputType.EMAIL, value=email)
                )
                duration = (time.monotonic() - start) * 1000
                if res.status.value == "SUCCESS" and res.identifiers:
                    ids = [
                        DiscoveredIdentifier(
                            type="google_gaia_id",
                            value=item.value,
                            normalized_value=item.normalized_value,
                            source=self.name,
                            confidence=0.99,
                        )
                        for item in res.identifiers
                    ]
                    return self._result(
                        EmailSourceStatus.FOUND,
                        account_exists=True,
                        confidence=0.99,
                        identifiers=ids,
                        evidence={"ghunt": True},
                        response_time_ms=duration,
                    )
            except Exception:
                pass

        # 2. Passive Google Account lookup via public web lookup / endpoint check
        client: httpx.AsyncClient = context.get("client") if context else None
        own_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
            own_client = True

        try:
            url = f"https://mail.google.com/mail/gxlu?email={email}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = await client.get(url, headers=headers)
            duration = (time.monotonic() - start) * 1000

            # If response contains 'COMPASS' cookie or specific headers, Google account exists
            if res.status_code == 200:
                cookies = res.headers.get("Set-Cookie", "")
                if "COMPASS" in cookies or "GAPS" in cookies or res.cookies.get("COMPASS"):
                    identifiers = [
                        DiscoveredIdentifier(
                            type="domain",
                            value="gmail.com",
                            normalized_value="gmail.com",
                            source=self.name,
                            confidence=0.95,
                        )
                    ]
                    return self._result(
                        EmailSourceStatus.FOUND,
                        account_exists=True,
                        confidence=0.95,
                        identifiers=identifiers,
                        evidence={"google_account": True},
                        response_time_ms=duration,
                        message="Google Account observed.",
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
