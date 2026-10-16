"""Event bus for Server-Sent Events, local and cross-process.

Sync request handlers (FastAPI runs them in a thread pool) publish; each SSE client
owns an asyncio.Queue on the server loop. publish() is thread-safe.

Cross-process: every event is also published on a Redis channel of the FalkorDB server (it speaks
Redis), tagged with this process's id. The API runs listen_forever() and forwards events from other
processes (the Slack/Discord bots, the CLI) to its own SSE clients, so a drift a bot detects shows up
live on every dashboard.

Events: {"type": "drift" | "message" | "resolved" | "ticket" | "pr" | "rebuild", "org": ..., ...payload}
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque

CHANNEL = "drift-monitor:events"
_ORIGIN = f"{os.getpid()}-{id(object())}"
log = logging.getLogger("bus")

_lock = threading.Lock()
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue, str]] = []
recent: deque = deque(maxlen=50)  # last events, for clients that connect later and for tests
version = 0  # bumped on every published event; api/cache.py uses it to invalidate cached reads


def publish(event_type: str, **payload) -> dict:
    from graph.db import current_org

    evt = {"type": event_type, "at": time.time(), "org": current_org(), **payload}
    _deliver(evt)
    try:  # cross-process fan-out; never let a broker hiccup break the request that published
        from graph.db import get_db

        get_db().connection.publish(CHANNEL, json.dumps({"origin": _ORIGIN, "event": evt}, default=str))
    except Exception as e:  # noqa: BLE001
        log.debug("redis publish failed: %s", e)
    return evt


def _deliver(evt: dict) -> None:
    """Local delivery: recent buffer, cache version bump, SSE subscribers of the event's org."""
    global version
    recent.append(evt)
    with _lock:
        version += 1
    with _lock:
        subs = list(_subscribers)
    for loop, q, org in subs:
        if org != evt["org"]:  # tenants never see each other's events
            continue
        try:
            loop.call_soon_threadsafe(q.put_nowait, evt)
        except RuntimeError:  # loop closed: subscriber is gone
            pass


def listen_forever(stop: threading.Event | None = None) -> None:
    """Forwards events published by OTHER processes to this process's subscribers. Run in a daemon thread."""
    from graph.db import get_db

    while not (stop and stop.is_set()):
        try:
            ps = get_db().connection.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(CHANNEL)
            while not (stop and stop.is_set()):
                msg = ps.get_message(timeout=1.0)
                if not msg:
                    continue
                data = json.loads(msg["data"])
                if data.get("origin") != _ORIGIN:
                    _deliver(data["event"])
        except Exception as e:  # noqa: BLE001 - reconnect after broker restarts
            log.warning("event listener reconnecting: %s", e)
            time.sleep(2)


def start_listener() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=listen_forever, args=(stop,), daemon=True, name="bus-listener").start()
    return stop


def subscribe(org: str = "default") -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _lock:
        _subscribers.append((asyncio.get_running_loop(), q, org))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers[:] = [(l, x, o) for l, x, o in _subscribers if x is not q]


async def stream(q: asyncio.Queue, heartbeat: float = 15.0):
    """Yields SSE frames; a comment line every `heartbeat` s keeps proxies from closing the connection."""
    yield "retry: 3000\n\n"
    try:
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=heartbeat)
                yield f"event: {evt['type']}\ndata: {json.dumps(evt, default=str)}\n\n"
            except TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        unsubscribe(q)
