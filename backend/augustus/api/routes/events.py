"""SSE (Server-Sent Events) endpoint for real-time frontend updates.

Streams data-change events so the frontend can immediately refresh
when the MCP server (or any other writer) modifies data.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from augustus.api.dependencies import get_memory
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"])

# How often the SSE loop checks for new events (seconds)
_POLL_INTERVAL = 2.0

# How often to prune old events (every N poll cycles)
_PRUNE_EVERY = 30  # ~60 seconds at 2s poll


async def _event_stream(
    memory: MemoryService,
    request: Request,
) -> None:
    """Async generator that yields SSE-formatted events."""
    last_id = 0

    # Seed last_id to current max so we don't replay history on connect
    rows = await memory.poll_events(after_id=0)
    if rows:
        last_id = max(r["id"] for r in rows)

    cycle = 0

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            rows = await memory.poll_events(after_id=last_id)
            for row in rows:
                event_data = {
                    "type": row["event_type"],
                    "agent_id": row["agent_id"],
                    "payload": json.loads(row["payload"]) if row["payload"] else {},
                }
                yield f"id: {row['id']}\nevent: update\ndata: {json.dumps(event_data)}\n\n"
                last_id = row["id"]

            # Periodic prune
            cycle += 1
            if cycle >= _PRUNE_EVERY:
                cycle = 0
                try:
                    await memory.prune_events(keep_seconds=300)
                except Exception:
                    pass  # Non-critical

            await asyncio.sleep(_POLL_INTERVAL)
    except (asyncio.CancelledError, GeneratorExit):
        # Client disconnected or server shutting down — exit cleanly
        return


@router.get("/events")
async def event_stream(
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> StreamingResponse:
    """SSE endpoint streaming real-time data-change notifications."""
    return StreamingResponse(
        _event_stream(memory, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
