"""Optional bounded adviser using Gemini. Only pivot metadata is sent — no personal data."""

import asyncio
import json
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pivot_id: int = Field(ge=0)
    reason: str = Field(max_length=500)


async def advise(decision, settings):
    if not settings.ai_adviser_enabled:
        return decision, {"status": "DISABLED"}
    if not settings.gemini_api_key:
        return decision, {"status": "AUTH_REQUIRED", "reason": "Set GEMINI_API_KEY in .env"}
    if len(decision.pivots) < 2:
        return decision, {"status": "NOT_NEEDED"}

    options = [
        dict(id=i, connector=p.connector_name, input_type=p.connector_input.type, stage=p.stage)
        for i, p in enumerate(decision.pivots)
    ]
    # Only structured pivot metadata leaves the machine. No bios, names, URLs, or raw data.
    prompt = (
        "You are an OSINT collection adviser. "
        "Choose ONE pivot_id from the list to prioritize next. "
        "Do not invent actions, connectors, or evidence. "
        "Every connector has bounded coverage; do not claim hundreds of sites or full coverage. "
        "Respond with JSON only.\n\nPivots:\n" + json.dumps(options)
    )
    model = settings.ai_model or "gemini-2.5-flash"
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
        async with client.aio as api, asyncio.timeout(25):
            response = await api.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "pivot_id": {"type": "INTEGER"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["pivot_id", "reason"],
                    },
                    max_output_tokens=1024,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                    if model.startswith("gemini-2.5-flash")
                    else None,
                    temperature=0.0,
                ),
            )
        advice = Advice.model_validate_json(response.text or "")
        if advice.pivot_id >= len(decision.pivots):
            raise ValueError("Adviser returned out-of-range pivot_id")
        chosen = decision.pivots[advice.pivot_id]
        pivots = (chosen,) + tuple(p for i, p in enumerate(decision.pivots) if i != advice.pivot_id)
        return replace(decision, pivots=pivots), {"status": "APPLIED", **advice.model_dump()}
    except Exception as exc:
        return decision, {
            "status": "FALLBACK",
            "reason": type(exc).__name__,
            "http_status": getattr(exc, "code", None),
        }
