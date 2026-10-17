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


def plain_text(text: str) -> str:
    """Slack mrkdwn -> plain text for extraction: code fences and inline code marks dropped (a message typed in the
    code formatter arrives as ```...```), HTML entities unescaped. Other markup (links, mentions) is left as is."""
    import html
    import re

    text = re.sub(r"```\s*(.*?)\s*```", r"\1", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return html.unescape(text).strip()


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
            text=plain_text(msg.get("text", "")),
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
        text=plain_text(msg.get("text", "")),
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


# ---------------------------------------------------------------- a connected team's workspace (not the demo)


def _slack_identity(g, u: dict) -> str:
    """A Slack member -> their Person, with name, job title, email and groups (admins) from their profile."""
    from pipeline import identity

    p = u.get("profile") or {}
    groups = ["admins"] if u.get("is_admin") or u.get("is_owner") else []
    return identity.resolve(
        g, "slack", f"slack:{u['id']}", u.get("name"), p.get("real_name") or u.get("real_name"), p.get("email"), p.get("title") or None, groups
    )


class TeamPeople:
    """Slack user id -> Person id for a connected team, through pipeline.identity (who's who), instead of the demo's
    hand-written people.json. Looks a user up once (users.info) and caches the answer."""

    def __init__(self, c: WebClient):
        self.c = c
        self.cache: dict[str, str] = {}

    def __call__(self, user_id: str | None) -> str:
        from graph.db import get_graph

        if not user_id:
            return "unknown"
        if user_id not in self.cache:
            try:
                u = self.c.users_info(user=user_id)["user"]
            except Exception:  # noqa: BLE001 - keep the message, attribute it to the raw id
                u = {"id": user_id, "name": user_id}
            self.cache[user_id] = _slack_identity(get_graph(), u)
        return self.cache[user_id]

    def forget(self, user_id: str) -> None:
        self.cache.pop(user_id, None)


def sync_directory(g, c: WebClient) -> int:
    """Every human in the workspace -> a Person with their title and groups; Slack user groups become groups too
    (they decide who may see restricted documents). Returns how many people were read."""
    n = 0
    for u in paged(c.users_list, "members", limit=200):
        if u.get("deleted") or u.get("is_bot") or u.get("id") == "USLACKBOT":
            continue
        _slack_identity(g, u)
        n += 1
    try:  # needs the usergroups:read scope; without it, people just have no Slack groups
        for grp in c.usergroups_list(include_users=True).get("usergroups", []):
            handle = grp.get("handle")
            for uid in grp.get("users") or []:
                g.query(
                    """MATCH (p:Person)-[:HAS_ACCOUNT]->(:Account {id: $a})
                       SET p.groups = coalesce(p.groups, []) + [x IN [$h] WHERE NOT x IN coalesce(p.groups, [])]""",
                    {"a": f"slack:{uid}", "h": handle},
                )
    except Exception:  # noqa: BLE001
        pass
    return n


def fetch_channels(c: WebClient, channels: list[dict], people, oldest: float | None = None, limit: int = 2000) -> list:
    """History (with thread replies) of the given channels [{id, name}], newest `limit` messages at most."""
    events: list = []
    for ch in channels:
        kw = {"channel": ch["id"], "limit": 200, **({"oldest": str(oldest)} if oldest else {})}
        for m in paged(c.conversations_history, "messages", **kw):
            if len(events) >= limit:
                return events
            if keep(m, ch["id"], {}):
                events.append(to_event(m, ch["name"], ch["id"], people, {}))
            if m.get("reply_count"):
                for x in paged(c.conversations_replies, "messages", channel=ch["id"], ts=m["ts"], limit=200):
                    if x["ts"] != m["ts"] and keep(x, ch["id"], {}):
                        events.append(to_event(x, ch["name"], ch["id"], people, {}))
    return events
