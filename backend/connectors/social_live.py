"""Bounded Social Analyzer public-profile checks using its JSON contract."""

import asyncio
import json
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .schemas import CandidateProfile, ConnectorResult, ConnectorRunStatus, ObservationArtifact


async def enrich_live(candidate: CandidateProfile) -> ConnectorResult:
    def result(status, **kwargs):
        return ConnectorResult(
            connector="social_analyzer", connector_version=tool_version, status=status, **kwargs
        )

    tool_version = "uninstalled"
    try:
        tool_version = version("social-analyzer")
    except PackageNotFoundError:
        return result(ConnectorRunStatus.UNAVAILABLE, message="Install the live extra.")
    site = {"github.com": "github", "www.reddit.com": "reddit", "reddit.com": "reddit"}.get(
        urlsplit(candidate.canonical_url).hostname
    )
    if site is None or not re.fullmatch(r"[\w][\w.-]{0,63}", candidate.username or ""):
        return result(
            ConnectorRunStatus.UNAVAILABLE,
            message="No reviewed Social Analyzer mapping for this profile.",
        )
    with TemporaryDirectory(prefix="deus-social-") as directory:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "social-analyzer",
            "--username",
            candidate.username,
            "--websites",
            site,
            "--output",
            "json",
            "--options",
            "link,rate,title",
            "--profiles",
            "all",
            "--method",
            "find",
            "--timeout",
            "8",
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=25)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
    try:
        raw = json.loads(stdout)
        if not isinstance(raw, dict) or not all(
            isinstance(raw.get(key), list) for key in ("detected", "unknown", "failed")
        ):
            raise ValueError("Unsupported JSON contract")
    except (ValueError, TypeError):
        return result(
            ConnectorRunStatus.FAILED,
            message="Social Analyzer returned invalid JSON.",
            metadata={
                "exit_code": process.returncode,
                "stderr_tail": stderr.decode(errors="replace")[-2000:],
            },
        )
    observations = []
    candidate_host = urlsplit(candidate.canonical_url).hostname or ""
    for item in raw["detected"]:
        link = item.get("link", "")
        if not link.startswith("https://"):
            continue
        # Accept any confirmed link on the same platform host — SA confirmed existence.
        link_host = urlsplit(link).hostname or ""
        if link_host != candidate_host:
            continue
        observations.append(
            ObservationArtifact(
                signal_type="PUBLIC_PROFILE_EXISTENCE",
                value=True,
                reliability=0.7,
                profile_url=candidate.canonical_url,
                source_url=item["link"],
                raw_data=item,
            )
        )
        if item.get("title"):
            observations.append(
                ObservationArtifact(
                    signal_type="PAGE_TITLE",
                    value=item["title"],
                    reliability=0.7,
                    profile_url=candidate.canonical_url,
                    source_url=item["link"],
                    raw_data=item,
                )
            )
    status = ConnectorRunStatus.SUCCESS if observations else ConnectorRunStatus.NO_RESULTS
    incomplete = bool(raw["failed"] or raw["unknown"] or process.returncode)
    if incomplete:
        status = ConnectorRunStatus.PARTIAL if observations else ConnectorRunStatus.FAILED
    return result(
        status,
        observations=observations,
        raw_records=[raw],
        request_count=sum(len(raw[key]) for key in ("detected", "failed", "unknown")),
        metadata={"mode": "live", "site": site},
        message="Some profile checks failed or were inconclusive." if incomplete else None,
    )
