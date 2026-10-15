"""The common event format every connector produces, plus small shared helpers."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# BD-101, bd 101, "Fixes BD-101", "(BD-107)". Ticket IDs are the hard-link signal.
TICKET_REF = re.compile(r"\b([A-Z]{2,5})-(\d{1,5})\b")


@dataclass
class Event:
    source: str                 # slack | discord | github | tickets
    kind: str                   # message | ticket | pull_request
    id: str                     # stable, globally unique; scenario ids when available
    author: str                 # Person id (resolved by the connector)
    ts: str                     # ISO-8601 UTC, when the thing happened
    text: str
    url: str = ""
    channel: str | None = None
    thread_of: str | None = None   # parent message id for replies
    extra: dict = field(default_factory=dict)  # kind-specific fields (ticket state, PR number, ...)

    @property
    def ticket_refs(self) -> list[str]:
        return find_ticket_refs(self.text)


def find_ticket_refs(text: str) -> list[str]:
    seen: list[str] = []
    for prefix, num in TICKET_REF.findall(text or ""):
        ref = f"{prefix}-{num}"
        if ref not in seen:
            seen.append(ref)
    return seen


def to_ms(iso: str | None) -> int | None:
    """ISO-8601 -> epoch milliseconds. The graph stores times as ints so Cypher can compare them."""
    if not iso:
        return None
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def from_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
