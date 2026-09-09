"""Explicit email self-audit only. Never contributes identity-correlation evidence."""

import re
from urllib.parse import quote

import httpx

from backend.core.config import get_settings

from .base import BaseConnector
from .schemas import (
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ObservationArtifact,
    ProducedArtifactType,
)


class HIBPConnector(BaseConnector):
    name = "hibp"
    version = "hibp-api-v3"
    documentation_url = "https://haveibeenpwned.com/API/v3"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.EMAIL}),
        produced_artifacts=frozenset({ProducedArtifactType.OBSERVATION}),
        requires_auth=True,
        live_supported=True,
    )

    @property
    def availability(self):
        settings = get_settings()
        return (
            ConnectorAvailability.DISABLED
            if not settings.hibp_enabled
            else ConnectorAvailability.AUTH_REQUIRED
            if not settings.hibp_api_key
            else ConnectorAvailability.AVAILABLE
        )

    async def discover(self, connector_input):
        if self.availability != ConnectorAvailability.AVAILABLE:
            return self._result(
                ConnectorRunStatus(self.availability.value),
                message="Enable HIBP and set HIBP_API_KEY for an explicit self-audit email",
            )
        email = connector_input.value
        if connector_input.type != ConnectorInputType.EMAIL or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", email
        ):
            return self._unsupported_input(connector_input)
        source = f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(email, safe='')}"
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            try:
                response = await client.get(
                    source,
                    params={"truncateResponse": "true"},
                    headers={
                        "hibp-api-key": get_settings().hibp_api_key.get_secret_value(),
                        "User-Agent": "Deus-defensive-self-audit/0.3",
                    },
                )
            except httpx.HTTPError as exc:
                return self._result(
                    ConnectorRunStatus.FAILED, request_count=1, message=type(exc).__name__
                )
        if response.status_code != 200:
            status = {
                404: ConnectorRunStatus.NO_RESULTS,
                401: ConnectorRunStatus.AUTH_REQUIRED,
                403: ConnectorRunStatus.AUTH_REQUIRED,
                429: ConnectorRunStatus.RATE_LIMITED,
            }.get(response.status_code, ConnectorRunStatus.FAILED)
            return self._result(
                status,
                request_count=1,
                message=f"HIBP HTTP {response.status_code}",
                metadata={"self_audit_only": True},
            )
        try:
            raw = response.json()
            if not isinstance(raw, list) or len(raw) > 1000:
                raise ValueError()
            names = [item["Name"] for item in raw if isinstance(item.get("Name"), str)]
            if len(names) != len(raw):
                raise ValueError()
        except (ValueError, KeyError, AttributeError):
            return self._result(
                ConnectorRunStatus.FAILED, request_count=1, message="Invalid HIBP response"
            )
        return self._result(
            ConnectorRunStatus.SUCCESS,
            request_count=1,
            observations=[
                ObservationArtifact(
                    signal_type="BREACH_EXPOSURE",
                    value=names,
                    source_url=source,
                    reliability=1.0,
                    raw_data={"breach_names": names},
                )
            ],
            metadata={"self_audit_only": True, "breach_names": names},
            message="Breach exposure only; no passwords retrieved or identity score impact.",
        )
