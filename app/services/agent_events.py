"""
In-process pub/sub for agent activity events.

The orchestrator + agents publish small JSON events ('agent_started',
'agent_progress', 'agent_completed', 'authenticator_review', etc.); the
SSE endpoint subscribes and streams them to the dashboard.

This is intentionally tiny — single process, no Redis, no Kafka. Each
generation request gets its own AgentEventBus instance so multiple
concurrent users don't see each other's events.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    type: str                       # e.g. "agent_started", "agent_completed"
    agent: str                      # e.g. "WritingAgent#1", "AuthenticatorAgent", "Captain"
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        # SSE wire format
        data = {
            "type": self.type,
            "agent": self.agent,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class AgentEventBus:
    """A bounded queue subscribers can pull from. One bus per generation session."""

    def __init__(self, session_id: str | None = None, maxsize: int = 1000) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._queue: queue.Queue[AgentEvent] = queue.Queue(maxsize=maxsize)
        self._closed = False
        self._lock = threading.Lock()

    def publish(self, event_type: str, agent: str, **payload: Any) -> None:
        if self._closed:
            return
        evt = AgentEvent(
            type=event_type,
            agent=agent,
            session_id=self.session_id,
            payload=payload,
        )
        try:
            self._queue.put_nowait(evt)
        except queue.Full:
            pass  # drop on full — the dashboard catches up in next event

    def drain(self, timeout: float = 0.5) -> list[AgentEvent]:
        out: list[AgentEvent] = []
        try:
            evt = self._queue.get(timeout=timeout)
            out.append(evt)
            while True:
                try:
                    out.append(self._queue.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            pass
        return out

    def close(self) -> None:
        with self._lock:
            self._closed = True


# Global registry — keyed by session_id so the SSE endpoint can find a bus
_REGISTRY: dict[str, AgentEventBus] = {}
_REGISTRY_LOCK = threading.Lock()


def register_bus(bus: AgentEventBus) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY[bus.session_id] = bus


def get_bus(session_id: str) -> AgentEventBus | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(session_id)


def unregister_bus(session_id: str) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY.pop(session_id, None)


def new_session() -> AgentEventBus:
    """Create + register a new bus, return it. Caller is responsible for unregistering."""
    bus = AgentEventBus()
    register_bus(bus)
    return bus
