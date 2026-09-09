"""Bounded Social Analyzer public-profile checks using its JSON contract."""

import asyncio
import importlib.util
import json
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from backend.normalization.urls import canonicalize_url

from .schemas import CandidateProfile, ConnectorResult, ConnectorRunStatus, ObservationArtifact

SUPPORTED_HOSTS = {
    "github.com",
    "reddit.com",
    "dev.to",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "news.ycombinator.com",
    "medium.com",
    "gitlab.com",
    "mastodon.social",
    "t.me",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "tumblr.com",
    "keybase.io",
    "steamcommunity.com",
    "twitch.tv",
    "stackoverflow.com",
    "pastebin.com",
    "facebook.com",
    "bsky.app",
    "threads.net",
    "threads.com",
    "soundcloud.com",
    "open.spotify.com",
    "behance.net",
    "dribbble.com",
    "codepen.io",
    "replit.com",
    "last.fm",
    "linktr.ee",
}


def site_for_url(url):
    """Select only a platform actually present in the installed SA database."""
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if host not in SUPPORTED_HOSTS:
        return None
    spec = importlib.util.find_spec("social-analyzer")
    if spec is None:
        return None
    try:
        entries = json.loads((Path(spec.origin).parent / "data/sites.json").read_text())[
            "websites_entries"
        ]
        for entry in entries:
            parsed = urlsplit(entry["url"])
            if (parsed.hostname or "").removeprefix("www.") == host:
                return f"{parsed.scheme}://{parsed.netloc}/"
    except (OSError, ValueError, KeyError):
        return None
    return None


def same_profile(left, right):
    try:
        return canonicalize_url(left) == canonicalize_url(right)
    except ValueError:
        return False


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
    site = site_for_url(candidate.canonical_url)
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
        if raw == {} and process.returncode == 0:
            return result(
                ConnectorRunStatus.PARTIAL,
                message="Social Analyzer returned no usable checks for this platform; "
                "profile existence remains unverified.",
                raw_records=[raw],
                metadata={"site": site, "mode": "live"},
            )
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
    for item in raw["detected"]:
        link = item.get("link", "")
        if not link.startswith("https://"):
            continue
        # A result elsewhere on the host is not evidence for this account.
        if not same_profile(link, candidate.canonical_url):
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
