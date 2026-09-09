"""HaveIBeenPwned API adapter for defensive self-audit."""

from __future__ import annotations

import time
from typing import Any

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class HIBPAdapter(BaseEmailSource):
    name = "hibp"
    category = "breach"
    cost = 3
    expected_latency_ms = 600
    reliability = 0.99
    priority = 30

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        hibp_conn = context.get("hibp_connector") if context else None

        if hibp_conn:
            try:
                from backend.connectors.schemas import ConnectorInput, ConnectorInputType
                res = await hibp_conn.discover(
                    ConnectorInput(type=ConnectorInputType.EMAIL, value=email)
                )
                duration = (time.monotonic() - start) * 1000
                if res.status.value == "SUCCESS":
                    breach_names = res.metadata.get("breach_names", [])
                    identifiers = [
                        DiscoveredIdentifier(
                            type="breach",
                            value=b_name,
                            normalized_value=b_name.casefold(),
                            source=self.name,
                            confidence=0.99,
                        )
                        for b_name in breach_names
                    ]
                    return self._result(
                        EmailSourceStatus.FOUND,
                        account_exists=bool(breach_names),
                        confidence=0.99,
                        identifiers=identifiers,
                        evidence={"breaches": breach_names},
                        response_time_ms=duration,
                        message=f"Observed in {len(breach_names)} breach record(s).",
                    )
            except Exception:
                pass

        return self._result(
            EmailSourceStatus.UNKNOWN,
            message="HIBP self-audit requires API key and explicit user consent.",
            response_time_ms=(time.monotonic() - start) * 1000,
        )
