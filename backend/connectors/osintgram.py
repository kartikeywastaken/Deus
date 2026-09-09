"""Real restricted Osintgram integration; existing operator session only."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.core.config import get_settings

from .base import BaseConnector
from .process import run_process
from .profile_links import profile_link
from .safe_http import validate_url
from .schemas import (
    CandidateProfile,
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    ProducedArtifactType,
)


class OsintgramConnector(BaseConnector):
    name = "osintgram"
    version = "c8ba1f0-public-profile-only-v1"
    documentation_url = "https://github.com/Datalux/Osintgram"
    live_message = "Restricted public-profile adapter requires an explicit operator session file."
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.INSTAGRAM_PROFILE}),
        produced_artifacts=frozenset({ProducedArtifactType.PROFILE}),
        supports_discovery=False,
        supports_enrichment=True,
        requires_auth=True,
        live_supported=True,
    )

    @property
    def availability(self):
        s = get_settings()
        if not s.osintgram_enabled:
            return ConnectorAvailability.DISABLED
        if (
            not s.osintgram_python
            or not Path(s.osintgram_python).is_file()
            or not (Path(s.osintgram_source) / "src/Osintgram.py").is_file()
        ):
            return ConnectorAvailability.UNAVAILABLE
        if not s.osintgram_session_file or not Path(s.osintgram_session_file).is_file():
            return ConnectorAvailability.AUTH_REQUIRED
        return ConnectorAvailability.AVAILABLE

    async def discover(self, connector_input):
        target = profile_link(connector_input.value)
        if connector_input.type not in self.accepts or not target or target[0] != "instagram":
            return self._unsupported_input(connector_input)
        if self.availability != ConnectorAvailability.AVAILABLE:
            return self._result(
                ConnectorRunStatus(self.availability.value), message=self.live_message
            )
        s = get_settings()
        try:
            python_path, source_path, session_path = await asyncio.to_thread(
                lambda: tuple(
                    str(Path(v).absolute())
                    for v in (s.osintgram_python, s.osintgram_source, s.osintgram_session_file)
                )
            )
            with TemporaryDirectory(prefix="deus-osintgram-") as directory:
                code, out, _ = await run_process(
                    python_path,
                    str(Path(__file__).with_name("osintgram_public.py")),
                    source_path,
                    session_path,
                    target[1],
                    cwd=directory,
                    budget_seconds=20,
                    max_bytes=100_000,
                )
            raw = json.loads(out)
            status = ConnectorRunStatus(raw["status"])
            if code or status != ConnectorRunStatus.SUCCESS:
                return self._result(status, message=raw.get("message", "Osintgram lookup failed"))
            user = raw["user"]
            if (
                user.get("is_private") is not False
                or user["username"].casefold() != target[1].casefold()
            ):
                raise ValueError("Unexpected public profile")
            links = []
            for link in [user.get("external_url")] + [
                x.get("url") for x in user.get("bio_links", [])
            ]:
                try:
                    if link and validate_url(link) not in links:
                        links.append(link)
                except ValueError:
                    continue
            return self._result(
                ConnectorRunStatus.SUCCESS,
                request_count=1,
                profiles=[
                    CandidateProfile(
                        platform="instagram",
                        username=user["username"],
                        canonical_url=target[2],
                        platform_account_id=str(user["pk"]),
                        display_name=user.get("full_name"),
                        bio=user.get("biography"),
                        external_links=links,
                        source_url=target[2],
                        discovered_by=[self.name],
                        raw=user,
                    )
                ],
                metadata={"public_fields_only": True, "upstream": self.version},
            )
        except Exception as exc:
            return self._result(ConnectorRunStatus.FAILED, message=type(exc).__name__)
