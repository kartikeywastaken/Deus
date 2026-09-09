"""Opt-in GitFive light mode: real public commits, no remote repository writes."""

import re
import shutil
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlsplit

from backend.core.config import get_settings

from .base import BaseConnector
from .process import run_process
from .schemas import (
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInputType,
    ConnectorRunStatus,
    IdentifierArtifact,
    IdentifierType,
    ObservationArtifact,
    ProducedArtifactType,
)


def parse_light(text):
    """Only the actual light-mode result section is accepted, not arbitrary console email text."""
    match = re.search(r'Emails? found for user "[^"\n]+"\s*:', text)
    if not match:
        return []
    return sorted(
        set(
            re.findall(
                r"(?m)^- ([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*$",
                text[match.end() :],
            )
        )
    )[:100]


class GitFiveConnector(BaseConnector):
    name = "gitfive"
    version = "gitfive-1.1.9-light"
    documentation_url = "https://github.com/mxrch/GitFive"
    capabilities = ConnectorCapabilities(
        accepted_inputs=frozenset({ConnectorInputType.GITHUB_PROFILE}),
        produced_artifacts=frozenset(
            {ProducedArtifactType.OBSERVATION, ProducedArtifactType.IDENTIFIER}
        ),
        supports_discovery=False,
        supports_enrichment=True,
        requires_auth=True,
        live_supported=True,
    )

    @property
    def availability(self):
        settings = get_settings()
        if not settings.gitfive_enabled:
            return ConnectorAvailability.DISABLED
        if not settings.gitfive_auth_ready:
            return ConnectorAvailability.AUTH_REQUIRED
        if not shutil.which(settings.gitfive_python or settings.gitfive_binary):
            return ConnectorAvailability.UNAVAILABLE
        return ConnectorAvailability.AVAILABLE

    async def discover(self, connector_input):
        if self.availability != ConnectorAvailability.AVAILABLE:
            return self._result(
                ConnectorRunStatus(self.availability.value),
                message="GitFive light requires installation, operator login and usage review.",
            )
        parsed = urlsplit(connector_input.value)
        username = parsed.path.strip("/")
        if (
            connector_input.type != ConnectorInputType.GITHUB_PROFILE
            or parsed.hostname != "github.com"
            or parsed.scheme != "https"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username)
        ):
            return self._unsupported_input(connector_input)
        with TemporaryDirectory(prefix="deus-gitfive-") as directory:
            settings = get_settings()
            command = (
                [settings.gitfive_python, "-c", "from gitfive.gitfive import main; main()"]
                if settings.gitfive_python
                else [settings.gitfive_binary]
            )
            code, out, _ = await run_process(
                *command, "light", username, cwd=directory, budget_seconds=25
            )
        output = re.sub(r"\x1b\[[0-9;]*m", "", out.decode(errors="replace"))
        emails = parse_light(output)
        if not emails:
            status = (
                ConnectorRunStatus.NO_RESULTS
                if "No email found for" in output and not code
                else ConnectorRunStatus.FAILED
            )
            return self._result(
                status,
                message="No public commit emails returned"
                if status == ConnectorRunStatus.NO_RESULTS
                else "GitFive failed; check operator login and CLI compatibility",
            )
        source = f"https://api.github.com/search/commits?q={quote('author:' + username)}"
        return self._result(
            ConnectorRunStatus.PARTIAL,
            request_count=2,
            observations=[
                ObservationArtifact(
                    signal_type="PUBLIC_COMMIT_EMAIL",
                    value=email,
                    profile_url=connector_input.value,
                    source_url=source,
                    reliability=0.5,
                    raw_data={"email": email, "source_mode": "gitfive light"},
                )
                for email in emails
            ],
            identifiers=[
                IdentifierArtifact(
                    type=IdentifierType.EMAIL,
                    value=email,
                    normalized_value=email.casefold(),
                    profile_url=connector_input.value,
                    source_url=source,
                    metadata={"authorship_unverified": True},
                )
                for email in emails
            ],
            metadata={"request_count_is_estimate": True, "mode": "light"},
            message="Bounded commit sample; author emails do not prove ownership.",
        )
