"""Optional bounded adviser. It can only prioritize already eligible pivot IDs."""

import json
from dataclasses import replace

import httpx
from pydantic import BaseModel, ConfigDict, Field


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pivot_id: int = Field(ge=0)
    reason: str = Field(max_length=500)


async def advise(decision, settings):
    if not settings.ai_adviser_enabled:
        return decision, {"status": "DISABLED"}
    if not settings.openai_api_key or not settings.ai_model:
        return decision, {"status": "AUTH_REQUIRED", "reason": "Configure key and model"}
    if len(decision.pivots) < 2:
        return decision, {"status": "NOT_NEEDED"}
    options = [
        dict(id=i, connector=p.connector_name, input_type=p.connector_input.type, stage=p.stage)
        for i, p in enumerate(decision.pivots)
    ]
    # No biographies, images, identifiers, or raw source text leave the machine.
    try:
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
                json={
                    "model": settings.ai_model,
                    "store": False,
                    "max_output_tokens": 300,
                    "instructions": "Choose a supplied pivot ID to prioritize for public "
                    "collection. Do not invent actions or evidence. Explain briefly.",
                    "input": json.dumps(options),
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "pivot_advice",
                            "strict": True,
                            "schema": Advice.model_json_schema(),
                        }
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        output = "".join(
            part.get("text", "")
            for item in payload.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        advice = Advice.model_validate_json(output)
        if advice.pivot_id >= len(decision.pivots):
            raise ValueError("Ineligible action")
        chosen = decision.pivots[advice.pivot_id]
        pivots = (chosen,) + tuple(p for i, p in enumerate(decision.pivots) if i != advice.pivot_id)
        return replace(decision, pivots=pivots), {"status": "APPLIED", **advice.model_dump()}
    except Exception as exc:
        return decision, {"status": "FALLBACK", "reason": type(exc).__name__}
