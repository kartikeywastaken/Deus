"""Isolated, bounded execution of the verified Maigret/Sherlock CSV contracts."""

import asyncio
import csv
import json
import re
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

from .discovery_sites import check_details, site_database
from .process import run_process
from .profile_links import profile_link
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
        database, sites, missing = site_database(tool)
        args = [binary, username, "--csv", "--folderoutput", directory, "--timeout", "8"]
        for site in sites:
            args.extend(["--site", site])
        if tool == "maigret":
            # Prevent bundled third-party mirrors from silently expanding scope.
            database["sites"] = {name: database["sites"][name] for name in sites}
            db_path = Path(directory) / "sites.json"
            db_path.write_text(json.dumps(database))
            args.extend(
                [
                    "--no-recursion",
                    "--no-extracting",
                    "--no-autoupdate",
                    "--db",
                    str(db_path),
                    "--no-progressbar",
                    "--no-color",
                    "--retries",
                    "0",
                    "-n",
                    "8",
                    "--dns-resolver",
                    "threaded",
                ]
            )
        else:
            # --local prevents Sherlock from auto-updating its DB during the run
            args.extend(["--local", "--no-txt"])

        exit_code, stdout, stderr = await run_process(*args, cwd=directory, budget_seconds=55)
        rows = await asyncio.to_thread(read_reports, directory)
        profiles = [
            CandidateProfile(
                platform=(profile_link(row["url_user"]) or (row["name"].casefold(),))[0],
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
            exit_code != 0 or not rows or any(row["exists"].casefold() == "unknown" for row in rows)
        )
        status = ConnectorRunStatus.SUCCESS if profiles else ConnectorRunStatus.NO_RESULTS
        if incomplete:
            status = ConnectorRunStatus.PARTIAL if rows else ConnectorRunStatus.FAILED
        return ConnectorResult(
            connector=tool,
            connector_version=tool_version,
            status=status,
            profiles=profiles,
            raw_records=rows,
            request_count=len(rows),
            metadata={
                "mode": "live",
                "exit_code": exit_code,
                "sites": sites,
                "unsupported_sites": missing,
                "site_checks": check_details(rows),
                "checked_sites": sorted({row["name"] for row in rows}),
                "coverage_note": "Exact installed definitions; third-party mirrors excluded.",
                "request_count_is_estimate": True,
                "stderr_tail": stderr.decode(errors="replace")[-2000:],
                "stdout_tail": stdout.decode(errors="replace")[-2000:] if incomplete else "",
            },
            message=(
                f"{sum(row['exists'].casefold() == 'unknown' for row in rows)} "
                f"of {len(rows)} checks inconclusive; no absence or identity conclusion."
                if incomplete and rows
                else "Tool exited without a parseable report."
                if incomplete
                else None
            ),
        )


def read_reports(directory: str) -> list[dict]:
    rows = []
    for path in Path(directory).glob("*.csv"):
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if {"exists", "url_user", "name"} <= set(reader.fieldnames or []):
                rows.extend(reader)
    return rows
