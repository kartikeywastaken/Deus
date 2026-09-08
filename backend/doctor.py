"""Read-only installation diagnostics: python -m backend.doctor [--embedding]."""

import argparse
import asyncio
import json
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import text

from backend.connectors import build_default_registry
from backend.db.session import AsyncSessionFactory, close_database


async def diagnose(embedding=False):
    result = {
        "collection_mode": "LIVE",
        "connectors": [await c.healthcheck() for c in build_default_registry()],
        "packages": {},
    }
    for name in ("maigret", "sherlock-project", "social-analyzer", "sentence-transformers"):
        try:
            result["packages"][name] = version(name)
        except PackageNotFoundError:
            result["packages"][name] = "UNAVAILABLE"
    try:
        async with AsyncSessionFactory() as session:
            result["postgresql"] = await session.scalar(text("SELECT version()"))
            result["pgvector"] = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            result["migration"] = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            result["jobs"] = [
                dict(r._mapping)
                for r in await session.execute(
                    text("SELECT status, count(*) AS count FROM investigation_jobs GROUP BY status")
                )
            ]
    except Exception as exc:
        result["database_error"] = type(exc).__name__
    if embedding:
        try:
            from backend.embeddings.service import MODEL, REVISION, encode

            vector = (await asyncio.to_thread(encode, ["Embedding health check"]))[0]
            result["embedding"] = {
                "model": MODEL,
                "revision": REVISION,
                "dimension": len(vector),
                "status": "AVAILABLE",
            }
        except Exception as exc:
            result["embedding"] = {"status": "UNAVAILABLE", "error": type(exc).__name__}
    await close_database()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding", action="store_true")
    print(json.dumps(asyncio.run(diagnose(parser.parse_args().embedding)), indent=2))
