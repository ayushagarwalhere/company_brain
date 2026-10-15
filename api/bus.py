"""In-process event bus for Server-Sent Events.

Sync request handlers (FastAPI runs them in a thread pool) publish; each SSE client
owns an asyncio.Queue on the server loop. publish() is thread-safe.

Events: {"type": "drift" | "message" | "resolved" | "ticket" | "pr" | "rebuild", ...payload}
"""
import asyncio
import json
import threading
import time
from collections import deque

_lock = threading.Lock()
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
recent: deque = deque(maxlen=50)  # last events, for clients that connect later and for tests


def publish(event_type: str, **payload) -> dict:
    evt = {"type": event_type, "at": time.time(), **payload}
    recent.append(evt)
    with _lock:
        subs = list(_subscribers)
    for loop, q in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, evt)
        except RuntimeError:  # loop closed: subscriber is gone
            pass
    return evt


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _lock:
        _subscribers.append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers[:] = [(l, x) for l, x in _subscribers if x is not q]


async def stream(q: asyncio.Queue, heartbeat: float = 15.0):
    """Yields SSE frames; a comment line every `heartbeat` s keeps proxies from closing the connection."""
    yield "retry: 3000\n\n"
    try:
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=heartbeat)
                yield f"event: {evt['type']}\ndata: {json.dumps(evt, default=str)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        unsubscribe(q)
