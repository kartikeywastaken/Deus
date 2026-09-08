"""Isolated, bounded execution of the verified Maigret/Sherlock CSV contracts."""

import asyncio
import csv
import re
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

from .schemas import CandidateProfile, ConnectorResult, ConnectorRunStatus


async def discover_live(tool: str, username: str) -> ConnectorResult:
    package = {"maigret": "maigret", "sherlock": "sherlock-project"}[tool]
    try:
        tool_version = version(package)
    except PackageNotFoundError:
        return ConnectorResult(
            connector=tool,
            connector_version="uninstalled",
            status=ConnectorRunStatus.UNAVAILABLE,
            message=f"Install the live extra to use {tool}.",
        )
    executable = Path(sys.executable).parent / tool
    binary = str(executable) if executable.exists() else shutil.which(tool)
    if binary is None:
        return ConnectorResult(
            connector=tool,
            connector_version=tool_version,
            status=ConnectorRunStatus.UNAVAILABLE,
            message=f"{tool} executable is missing.",
        )
    if not re.fullmatch(r"[\w][\w.-]{0,63}", username):
        return ConnectorResult(
            connector=tool,
            connector_version=tool_version,
            status=ConnectorRunStatus.NO_RESULTS,
            message="Username contains unsupported characters.",
        )
    with TemporaryDirectory(prefix=f"deus-{tool}-") as directory:
        args = [binary, username, "--csv", "--folderoutput", directory, "--timeout", "8"]
        # A bounded initial set; expansion decisions remain with the orchestrator.
        for site in ("GitHub", "Reddit", "Dev.to"):
            args.extend(["--site", site])
        if tool == "maigret":
            args.extend(["--no-recursion", "--no-extracting", "--no-autoupdate"])
        else:
            args.extend(["--local", "--no-txt"])
        process = await asyncio.create_subprocess_exec(
            *args,
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
        rows = await asyncio.to_thread(read_reports, directory)
        profiles = [
            CandidateProfile(
                platform=row["name"].casefold(),
                canonical_url=row["url_user"],
                username=username,
                source_url=row["url_user"],
                discovered_by=[tool],
                raw=row,
            )
            for row in rows
            if row["exists"].casefold() == "claimed" and row["url_user"].startswith("https://")
        ]
        incomplete = (
            process.returncode != 0
            or not rows
            or any(row["exists"].casefold() == "unknown" for row in rows)
        )
        status = ConnectorRunStatus.SUCCESS if profiles else ConnectorRunStatus.NO_RESULTS
        if incomplete:
            status = ConnectorRunStatus.PARTIAL if profiles else ConnectorRunStatus.FAILED
        return ConnectorResult(
            connector=tool,
            connector_version=tool_version,
            status=status,
            profiles=profiles,
            raw_records=rows,
            request_count=len(rows),
            metadata={
                "mode": "live",
                "exit_code": process.returncode,
                "sites": ["GitHub", "Reddit", "Dev.to"],
                "checked_sites": sorted({row["name"] for row in rows}),
                "coverage_note": "Maigret can include bundled mirrors of selected platforms.",
                "request_count_is_estimate": True,
                "stderr_tail": stderr.decode(errors="replace")[-2000:],
                "stdout_tail": stdout.decode(errors="replace")[-2000:] if incomplete else "",
            },
            message="Some checks failed or produced no parseable report." if incomplete else None,
        )


def read_reports(directory: str) -> list[dict]:
    rows = []
    for path in Path(directory).glob("*.csv"):
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if {"exists", "url_user", "name"} <= set(reader.fieldnames or []):
                rows.extend(reader)
    return rows
