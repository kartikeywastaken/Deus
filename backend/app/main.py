"""FastAPI entry point for the OSINT identity-correlation MVP."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.api import candidates, email_api, events, hypotheses, images, questions, reports, searches, username_api
from backend.connectors import build_default_registry
from backend.core.config import Settings, get_settings
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        },
    )


app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(searches.router)
app.include_router(email_api.router)
app.include_router(username_api.router)
app.include_router(candidates.router)
app.include_router(hypotheses.router)
app.include_router(questions.router)
app.include_router(reports.router)
app.include_router(images.router)
app.include_router(events.router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "database": "postgresql+pgvector",
        "collection_mode": "LIVE",
    }


@app.get("/api/config.js", tags=["config"], response_class=Response)
async def config_js() -> Response:
    """Serve same-origin runtime config for the frontend."""
    script = "window.OSINT_API_BASE = window.location.origin;\n"
    return Response(content=script, media_type="application/javascript")


@app.get("/api/connectors", tags=["connectors"])
async def connectors() -> dict[str, object]:
    registry = build_default_registry()
    return {
        "mode": "LIVE",
        "items": [
            {**(await connector.healthcheck()), "availability": connector.availability}
            for connector in registry
        ],
    }


frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
if frontend_directory.exists():
    app.mount("/", StaticFiles(directory=frontend_directory, html=True), name="frontend")
