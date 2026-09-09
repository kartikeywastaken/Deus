"""Opt-in, profile-ID-only GHunt. Never invokes its maps/calendar/face routines."""

import json
import re
import sys
from pathlib import Path

from backend.core.config import get_settings

from .base import BaseConnector
from .process import run_process
from .schemas import (
    CandidateProfile,
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ObservationArtifact,
    ProducedArtifactType,
)


class GHuntConnector(BaseConnector):
    name = "ghunt"
    version = "ghunt-2.3.4-profile-only"
    documentation_url = "https://github.com/mxrch/GHunt"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.EMAIL}),
        produced_artifacts=frozenset(
            {ProducedArtifactType.PROFILE, ProducedArtifactType.OBSERVATION}
        ),
        requires_auth=True,
        live_supported=True,
    )

    @property
    def availability(self):
        settings = get_settings()
        return (
            ConnectorAvailability.DISABLED
            if not settings.ghunt_enabled
            else ConnectorAvailability.AUTH_REQUIRED
            if not settings.ghunt_auth_ready
            else ConnectorAvailability.AVAILABLE
        )

    async def discover(self, connector_input):
        if self.availability != ConnectorAvailability.AVAILABLE:
            return self._result(
                ConnectorRunStatus(self.availability.value),
                message="Install GHunt and run ghunt login before enabling self-audit collection.",
            )
        if connector_input.type != ConnectorInputType.EMAIL or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", connector_input.value
        ):
            return self._unsupported_input(connector_input)
        settings = get_settings()
        try:
            code, out, _ = await run_process(
                settings.ghunt_python or sys.executable,
                str(Path(__file__).with_name("ghunt_public.py")),
                connector_input.value,
                budget_seconds=25,
            )
            raw = json.loads(out)
            status = ConnectorRunStatus(raw["status"])
            if status != ConnectorRunStatus.SUCCESS or code:
                return self._result(status, message=raw.get("message", "GHunt lookup failed"))
            gaia = raw.get("gaia_id", "")
            if not re.fullmatch(r"[0-9]{10,30}", gaia):
                raise ValueError("Invalid public account ID")
            url = f"https://www.google.com/maps/contrib/{gaia}"
            source = "https://people-pa.clients6.google.com/v2/people/lookup"
            return self._result(
                ConnectorRunStatus.SUCCESS,
                request_count=1,
                profiles=[
                    CandidateProfile(
                        platform="google",
                        platform_account_id=gaia,
                        canonical_url=url,
                        source_url=source,
                        raw=raw,
                        discovered_by=[self.name],
                    )
                ],
                observations=[
                    ObservationArtifact(
                        signal_type="PUBLIC_GOOGLE_PROFILE_ID",
                        value=gaia,
                        source_url=source,
                        profile_url=url,
                        reliability=0.8,
                        raw_data=raw,
                    )
                ],
                metadata={"request_count_is_estimate": True, "profile_only": True},
            )
        except FileNotFoundError:
            return self._result(ConnectorRunStatus.UNAVAILABLE, message="GHUNT_PYTHON not found")
        except (ValueError, KeyError):
            return self._result(ConnectorRunStatus.FAILED, message="Invalid GHunt profile response")
