"""Slack connector: channel history (incl. thread replies) -> Events."""

from datetime import UTC, datetime

from slack_sdk import WebClient

from config import settings
from connectors import scenario, seed_map

CHANNELS = ("product", "engineering", "support-escalations")


def client() -> WebClient:
    from slack_sdk.http_retry.builtin_handlers import ConnectionErrorRetryHandler, RateLimitErrorRetryHandler

    c = WebClient(token=settings.slack_bot_token)
    # Slack answers 429 + Retry-After under load (conversations.history is Tier 3): wait and retry
    c.retry_handlers.extend([RateLimitErrorRetryHandler(max_retry_count=5), ConnectionErrorRetryHandler(max_retry_count=3)])
    return c


def paged(call, key: str, **kwargs):
    """Yields items across every page of a cursor-paginated Slack Web API method."""
    cursor = None
    while True:
        r = call(**kwargs, cursor=cursor) if cursor else call(**kwargs)
        yield from r[key]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return


def channel_ids(c: WebClient) -> dict[str, str]:
    """name -> id for public channels the bot can see."""
    return {ch["name"]: ch["id"] for ch in paged(c.conversations_list, "channels", types="public_channel", limit=200)}


class PersonLookup:
    """Slack user id -> Person id, via the slack handle in people.json."""

    def __init__(self, c: WebClient):
        self.c = c
        self.by_handle = {p["slack"]: p["id"] for p in scenario.people()}
        self.cache: dict[str, str] = {}

    def __call__(self, user_id: str | None) -> str:
        if not user_id:
            return "unknown"
        if user_id not in self.cache:
            try:
                u = self.c.users_info(user=user_id)["user"]
                name = u.get("name", user_id)
            except Exception:  # noqa: BLE001 - fall back to the raw id
                name = user_id
            self.cache[user_id] = self.by_handle.get(name, f"slack:{name}")
        return self.cache[user_id]


def slack_ts_to_iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_event(msg: dict, channel_name: str, channel_id: str, people: PersonLookup, smap: dict):
    from pipeline.events import Event

    key = f"{channel_id}:{msg['ts']}"
    seeded = smap.get(key)
    parent = msg.get("thread_ts") if msg.get("thread_ts") != msg["ts"] else None
    if seeded:
        return Event(
            source="slack",
            kind="message",
            id=seeded["id"],
            author=seeded["author"],
            ts=seeded["ts"],
            text=msg.get("text", ""),
            url=permalink(channel_id, msg["ts"]),
            channel=channel_name,
            thread_of=seeded.get("thread_of"),
        )
    parent_id = None
    if parent:
        p = smap.get(f"{channel_id}:{parent}")
        parent_id = p["id"] if p else f"slack:{channel_id}:{parent}"
    return Event(
        source="slack",
        kind="message",
        id=f"slack:{key}",
        author=people(msg.get("user")),
        ts=slack_ts_to_iso(msg["ts"]),
        text=msg.get("text", ""),
        url=permalink(channel_id, msg["ts"]),
        channel=channel_name,
        thread_of=parent_id,
    )


def permalink(channel_id: str, ts: str) -> str:
    return f"https://slack.com/app_redirect?channel={channel_id}&message_ts={ts}"


SKIP_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "message_deleted"}


def keep(m: dict, channel_id: str, smap: dict) -> bool:
    """Human messages and our seeded scenario messages. Bot posts that aren't seeded (e.g. our own drift
    alerts) are skipped, or the monitor would read its alerts back as requirement changes."""
    if m.get("subtype") in SKIP_SUBTYPES:
        return False
    if m.get("bot_id") or m.get("subtype") == "bot_message":
        return f"{channel_id}:{m['ts']}" in smap
    return bool(m.get("text"))


def fetch_history(c: WebClient | None = None) -> list:
    c = c or client()
    ids = channel_ids(c)
    people = PersonLookup(c)
    smap = seed_map.load("slack")
    events = []
    for name in CHANNELS:
        if name not in ids:
            continue
        cid = ids[name]
        for m in paged(c.conversations_history, "messages", channel=cid, limit=200):
            if keep(m, cid, smap):
                events.append(to_event(m, name, cid, people, smap))
            if m.get("reply_count"):  # thread replies live behind conversations.replies, paginated too
                for x in paged(c.conversations_replies, "messages", channel=cid, ts=m["ts"], limit=200):
                    if x["ts"] != m["ts"] and keep(x, cid, smap):
                        events.append(to_event(x, name, cid, people, smap))
    return events
