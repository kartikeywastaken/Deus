"""Optional bounded adviser using Gemini. Only pivot metadata is sent — no personal data."""

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
        "Respond with JSON only.\n\nPivots:\n" + json.dumps(options)
    )
    model = settings.ai_model or "gemini-2.5-flash"
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Advice,
                max_output_tokens=256,
                temperature=0.0,
            ),
        )
        advice = response.parsed
        if not isinstance(advice, Advice):
            raise ValueError("Model returned unexpected schema")
        if advice.pivot_id >= len(decision.pivots):
            raise ValueError("Adviser returned out-of-range pivot_id")
        chosen = decision.pivots[advice.pivot_id]
        pivots = (chosen,) + tuple(p for i, p in enumerate(decision.pivots) if i != advice.pivot_id)
        return replace(decision, pivots=pivots), {"status": "APPLIED", **advice.model_dump()}
    except Exception as exc:
        return decision, {"status": "FALLBACK", "reason": type(exc).__name__}
