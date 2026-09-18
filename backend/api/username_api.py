"""Dedicated API endpoint for Username OSINT & Identity Discovery."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.config import Settings, get_settings
from backend.username_osint import UsernameOSINTEngine, UsernameOSINTResult

router = APIRouter(prefix="/api/osint", tags=["username_osint"])


class UsernameSearchRequest(BaseModel):
    username: str


@router.post("/username", response_model=UsernameOSINTResult)
async def discover_username(
    payload: UsernameSearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    username = payload.username.strip().lstrip("@")
    if not username or not re.fullmatch(r"[\w][\w.-]{0,63}", username):
        raise HTTPException(status_code=422, detail="Invalid username format.")

    github_token = settings.github_token.get_secret_value() if settings.github_token else None

    try:
        engine = UsernameOSINTEngine(github_token=github_token)
        result = await engine.discover(
            username,
            context={"github_token": github_token},
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Username OSINT error: {exc}") from exc
