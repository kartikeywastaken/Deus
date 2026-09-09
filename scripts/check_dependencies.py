#!/usr/bin/env python3
"""Real system readiness check. Run as: python scripts/check_dependencies.py"""

from __future__ import annotations

import asyncio
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT INSTALLED"


def _bin(name: str) -> str:
    path = shutil.which(name)
    if path:
        return f"FOUND ({path})"
    import pathlib

    venv_bin = pathlib.Path(sys.executable).parent / name
    if venv_bin.exists():
        return f"FOUND ({venv_bin})"
    return "MISSING"


async def _check_postgres() -> str:
    try:
        import asyncpg

        from backend.core.config import get_settings

        settings = get_settings()
        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=url, timeout=5)
        ver = await conn.fetchval("SELECT version()")
        pg = await conn.fetchrow(
            "SELECT default_version FROM pg_available_extensions WHERE name='vector'"
        )
        await conn.close()
        pgv = pg["default_version"] if pg else "NOT INSTALLED"
        return f"OK — {ver[:60]} | pgvector={pgv}"
    except Exception as exc:
        return f"ERROR: {exc}"


async def _check_migration() -> str:
    try:
        import asyncpg

        from backend.core.config import get_settings

        settings = get_settings()
        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=url, timeout=5)
        row = await conn.fetchrow(
            "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"
        )
        await conn.close()
        return row["version_num"] if row else "NO MIGRATIONS"
    except Exception as exc:
        return f"ERROR: {exc}"


def _row(name: str, status: str, note: str = "") -> str:
    parts = f"{name:<26} {status:<30}"
    if note:
        parts += f"  {note}"
    return parts


async def main() -> None:
    print("=" * 76)
    print("Deus — System Readiness Check")
    print("=" * 76)

    print("\n[Database]")
    pg = await _check_postgres()
    print(_row("PostgreSQL+pgvector", "OK" if pg.startswith("OK") else "ERROR", pg[:80]))
    mg = await _check_migration()
    print(_row("Alembic migrations", mg))

    print("\n[Python Packages]")
    packages = [
        ("fastapi", "fastapi"),
        ("sqlalchemy", "sqlalchemy"),
        ("asyncpg", "asyncpg"),
        ("alembic", "alembic"),
        ("pgvector", "pgvector"),
        ("httpx", "httpx"),
        ("pydantic", "pydantic"),
        ("sentence-transformers", "sentence-transformers"),
        ("Pillow", "Pillow"),
        ("imagehash", "imagehash"),
        ("maigret", "maigret"),
        ("sherlock-project", "sherlock-project"),
        ("social-analyzer", "social-analyzer"),
        ("rapidfuzz", "rapidfuzz"),
        ("tldextract", "tldextract"),
        ("aiohttp", "aiohttp"),
    ]
    for display, pkg in packages:
        v = _pkg(pkg)
        status = v if v != "NOT INSTALLED" else "MISSING"
        print(_row(display, status))

    print("\n[CLI Tools]")
    for binary, note in [("maigret", "Username OSINT"), ("sherlock", "Username OSINT")]:
        found = _bin(binary)
        status = "AVAILABLE" if "FOUND" in found else "MISSING"
        print(_row(binary, status, note))

    print("\n[Connectors]")
    try:
        from backend.connectors import build_default_registry

        registry = build_default_registry()
        for name, connector in registry._connectors.items():
            avail = connector.availability
            note = ""
            if (
                hasattr(connector, "live_message")
                and connector.live_message
                and connector.availability != "AVAILABLE"
            ):
                note = connector.live_message[:55]
            print(_row(name, avail, note))
    except Exception as exc:
        print(f"  ERROR loading registry: {exc}")

    print("\n[Optional Configuration]")
    from backend.core.config import get_settings

    settings = get_settings()
    print(_row("GITHUB_TOKEN", "SET" if settings.github_token else "NOT SET (rate limits apply)"))
    print(_row("AI_ADVISER", "ENABLED" if settings.ai_adviser_enabled else "DISABLED"))
    print(_row("GEMINI_API_KEY", "SET" if settings.gemini_api_key else "NOT SET"))

    print("\n[Embeddings]")
    try:
        from backend.embeddings.service import MODEL, REVISION

        print(_row("sentence-transformers", "IMPORTABLE", f"model={MODEL}"))
        print(_row("model revision", REVISION[:20] + "...", "lazy-loaded on first embed"))
    except ImportError as exc:
        print(_row("sentence-transformers", "IMPORT ERROR", str(exc)))

    print("\n" + "=" * 76)
    print("Run `python -m backend.doctor` for JSON output and job queue state.")
    print("=" * 76)


if __name__ == "__main__":
    asyncio.run(main())
