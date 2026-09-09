"""Dedicated API endpoint for high-performance Email OSINT & Identity Discovery."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.config import Settings, get_settings
from backend.email_osint import EmailOSINTEngine, EmailOSINTResult

router = APIRouter(prefix="/api/osint", tags=["email_osint"])

_email_engine = EmailOSINTEngine()


class EmailSearchRequest(BaseModel):
    email: str
    max_depth: int = Field(default=2, ge=1, le=5)
    self_audit_confirmed: bool = False


@router.post("/email", response_model=EmailOSINTResult)
async def discover_email(
    payload: EmailSearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    email = payload.email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Invalid email address format.")

    context = {
        "github_token": settings.github_token.get_secret_value() if settings.github_token else None,
        "self_audit_confirmed": payload.self_audit_confirmed,
    }

    try:
        result = await _email_engine.discover(email, context=context)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Email OSINT error: {exc}") from exc
