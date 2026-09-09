"""Resumable SSE stream; each poll releases its PostgreSQL connection."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.db.models import SearchEvent, SearchRun
from backend.db.session import AsyncSessionFactory

router = APIRouter(prefix="/api/searches", tags=["events"])


@router.get("/{search_id}/events")
async def events(search_id: UUID, request: Request, after: int = 0):
    try:
        cursor = max(0, int(request.headers.get("last-event-id", after)))
        if cursor > 9223372036854775807:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid event cursor") from exc
    async with AsyncSessionFactory() as session:
        if await session.get(SearchRun, search_id) is None:
            raise HTTPException(404, "search not found")

    async def stream():
        nonlocal cursor
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            async with AsyncSessionFactory() as session:
                rows = list(
                    await session.scalars(
                        select(SearchEvent)
                        .where(SearchEvent.search_run_id == search_id, SearchEvent.id > cursor)
                        .order_by(SearchEvent.id)
                        .limit(200)
                    )
                )
                status = await session.scalar(
                    select(SearchRun.status).where(SearchRun.id == search_id)
                )
            for row in rows:
                cursor = row.id
                data = json.dumps(
                    {
                        "type": row.kind,
                        "payload": row.payload,
                        "created_at": row.created_at.isoformat(),
                    }
                )
                yield f"id: {cursor}\nevent: update\ndata: {data}\n\n"
            if len(rows) < 200 and status in {"COMPLETED", "FAILED", "CANCELLED"}:
                yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
