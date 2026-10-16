"""Read-through cache for heavy GET endpoints.

Entries are keyed by (name, args) and stamped with the bus version: any write that goes
through the API publishes an event, bumps the version, and so invalidates everything at once.
A short TTL bounds staleness for writes made by other processes (bots, the build CLI).
"""

import threading
import time

from api import bus

TTL_S = 3.0
_lock = threading.Lock()
_store: dict[tuple, tuple[int, float, object]] = {}
stats = {"hits": 0, "misses": 0}


def cached(name: str, fn, *args, ttl: float = TTL_S):
    from graph.db import current_graph_name

    key = (current_graph_name(), name, args)
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] == bus.version and now - hit[1] < ttl:
            stats["hits"] += 1
            return hit[2]
    value = fn(*args)
    with _lock:
        _store[key] = (bus.version, now, value)
        stats["misses"] += 1
    return value


def clear() -> None:
    with _lock:
        _store.clear()
