"""FastAPI entry point for the OSINT identity-correlation MVP."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import candidates, hypotheses, questions, reports, searches
from backend.connectors import build_default_registry
from backend.core.config import get_settings
from backend.db.session import close_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    yield
    await close_database()


app = FastAPI(
    title="Osin Identity Correlation API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(searches.router)
app.include_router(candidates.router)
app.include_router(hypotheses.router)
app.include_router(questions.router)
app.include_router(reports.router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "database": "postgresql+pgvector",
        "mock_connectors": settings.mock_connectors,
    }


@app.get("/api/connectors", tags=["connectors"])
async def connectors() -> dict[str, object]:
    settings = get_settings()
    registry = build_default_registry(mock_connectors=settings.mock_connectors)
    return {
        "mode": "MOCK" if settings.mock_connectors else "LIVE",
        "items": [
            {
                "name": connector.name,
                "availability": connector.availability,
                "capabilities": connector.capabilities.model_dump(mode="json"),
            }
            for connector in registry
        ],
    }


frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
if frontend_directory.exists():
    app.mount("/", StaticFiles(directory=frontend_directory, html=True), name="frontend")
