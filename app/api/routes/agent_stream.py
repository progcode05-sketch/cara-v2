"""
Server-Sent-Events (SSE) endpoint for live agent flowchart in the dashboard.

Flow:
  1. Dashboard calls POST /agents/sessions  →  receives {session_id}
  2. Dashboard opens EventSource("/agents/sessions/{id}/stream")
  3. Dashboard calls POST /carousels/generate with body.session_id = id
  4. Orchestrator + agents publish events to the bus keyed by session_id
  5. Dashboard renders flowchart updates live as events stream in
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.agent_events import (
    AgentEventBus,
    get_bus,
    new_session,
    register_bus,
    unregister_bus,
)


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/sessions")
def create_session() -> dict[str, str]:
    """Allocate a fresh AgentEventBus and return its id."""
    bus = new_session()
    return {"session_id": bus.session_id}


@router.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str) -> StreamingResponse:
    bus = get_bus(session_id)
    if not bus:
        # Re-create on demand so a slow dashboard doesn't lose its bus
        bus = AgentEventBus(session_id=session_id)
        register_bus(bus)

    async def event_generator():
        # Initial heartbeat so the connection opens cleanly in browsers
        yield "retry: 1500\n\n"
        yield 'data: {"type":"connected","agent":"server","payload":{}}\n\n'
        deadline = time.time() + 600  # max 10 min per stream
        last_event = time.time()
        while time.time() < deadline:
            events = bus.drain(timeout=0.0)  # non-blocking
            if events:
                last_event = time.time()
                for evt in events:
                    yield evt.to_sse()
                    # If pipeline finalised, give 2s grace then close
                    if evt.type == "pipeline_finalised":
                        await asyncio.sleep(2.0)
                        return
            else:
                # heartbeat every ~10s to keep the stream alive
                if time.time() - last_event > 10:
                    yield ": heartbeat\n\n"
                    last_event = time.time()
                await asyncio.sleep(0.1)
        yield 'data: {"type":"timeout","agent":"server","payload":{}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/sessions/{session_id}")
def close_session(session_id: str) -> dict[str, str]:
    bus = get_bus(session_id)
    if bus:
        bus.close()
    unregister_bus(session_id)
    return {"status": "closed", "session_id": session_id}
