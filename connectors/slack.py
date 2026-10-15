"""Slack connector: channel history (incl. thread replies) -> Events."""
from datetime import datetime, timezone

from slack_sdk import WebClient

from config import settings
from connectors import scenario, seed_map

CHANNELS = ("product", "engineering", "support-escalations")


def client() -> WebClient:
    return WebClient(token=settings.slack_bot_token)


def channel_ids(c: WebClient) -> dict[str, str]:
    """name -> id for public channels the bot can see."""
    out, cursor = {}, None
    while True:
        r = c.conversations_list(types="public_channel", limit=200, cursor=cursor)
        out.update({ch["name"]: ch["id"] for ch in r["channels"]})
        cursor = r.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            return out


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
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_event(msg: dict, channel_name: str, channel_id: str, people: PersonLookup, smap: dict):
    from pipeline.events import Event

    key = f"{channel_id}:{msg['ts']}"
    seeded = smap.get(key)
    parent = msg.get("thread_ts") if msg.get("thread_ts") != msg["ts"] else None
    if seeded:
        return Event(source="slack", kind="message", id=seeded["id"], author=seeded["author"], ts=seeded["ts"],
                     text=msg.get("text", ""), url=permalink(channel_id, msg["ts"]), channel=channel_name,
                     thread_of=seeded.get("thread_of"))
    parent_id = None
    if parent:
        p = smap.get(f"{channel_id}:{parent}")
        parent_id = p["id"] if p else f"slack:{channel_id}:{parent}"
    return Event(source="slack", kind="message", id=f"slack:{key}", author=people(msg.get("user")),
                 ts=slack_ts_to_iso(msg["ts"]), text=msg.get("text", ""), url=permalink(channel_id, msg["ts"]),
                 channel=channel_name, thread_of=parent_id)


def permalink(channel_id: str, ts: str) -> str:
    return f"https://slack.com/app_redirect?channel={channel_id}&message_ts={ts}"


def fetch_history() -> list:
    c = client()
    ids = channel_ids(c)
    people = PersonLookup(c)
    smap = seed_map.load("slack")
    events = []
    for name in CHANNELS:
        if name not in ids:
            continue
        cid, cursor = ids[name], None
        while True:
            r = c.conversations_history(channel=cid, limit=200, cursor=cursor)
            for m in r["messages"]:
                if m.get("subtype") in ("channel_join", "channel_leave"):
                    continue
                events.append(to_event(m, name, cid, people, smap))
                if m.get("reply_count"):
                    replies = c.conversations_replies(channel=cid, ts=m["ts"], limit=200)["messages"]
                    events += [to_event(x, name, cid, people, smap) for x in replies if x["ts"] != m["ts"]]
            cursor = r.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    return events
