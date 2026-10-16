"""Discord connector: channel history -> Events.

Seeded messages are posted through per-channel webhooks (so each shows the
fictional author's name). Webhooks can't reply in a thread, so thread structure
for seeded messages comes from the seed map.
"""
import asyncio

import discord

from config import settings
from connectors import scenario, seed_map
from pipeline.events import Event

CHANNELS = ("engineering", "design", "random")


def _people_by_name() -> dict[str, str]:
    out = {}
    for p in scenario.people():
        out[p["discord"]] = p["id"]
        out[p["name"]] = p["id"]
    return out


def to_event(msg: discord.Message, smap: dict, people: dict[str, str]) -> Event:
    seeded = smap.get(str(msg.id))
    if seeded:
        return Event(source="discord", kind="message", id=seeded["id"], author=seeded["author"], ts=seeded["ts"],
                     text=msg.content, url=msg.jump_url, channel=msg.channel.name, thread_of=seeded.get("thread_of"))
    parent = None
    if msg.reference and msg.reference.message_id:
        ref = smap.get(str(msg.reference.message_id))
        parent = ref["id"] if ref else f"discord:{msg.reference.message_id}"
    name = msg.author.name
    return Event(source="discord", kind="message", id=f"discord:{msg.id}",
                 author=people.get(name, people.get(getattr(msg.author, "display_name", ""), f"discord:{name}")),
                 ts=msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), text=msg.content, url=msg.jump_url,
                 channel=msg.channel.name, thread_of=parent)


def keep(msg, smap: dict) -> bool:
    """Human messages and our webhook-seeded scenario messages; skip other bots (incl. our own drift alerts)."""
    if not msg.content:
        return False
    if str(msg.id) in smap:
        return True
    return not getattr(msg.author, "bot", False)


async def _fetch(limit: int) -> list[Event]:
    intents = discord.Intents.default()
    intents.message_content = True
    c = discord.Client(intents=intents)
    out: list[Event] = []
    smap, people = seed_map.load("discord"), _people_by_name()

    @c.event
    async def on_ready():
        try:
            guild = c.get_guild(int(settings.discord_guild_id))
            for ch in guild.text_channels:
                if ch.name in CHANNELS:
                    async for m in ch.history(limit=limit, oldest_first=True):
                        if keep(m, smap):
                            out.append(to_event(m, smap, people))
        finally:
            await c.close()

    await c.start(settings.discord_bot_token)
    return out


def fetch_history(limit: int = 2000) -> list[Event]:
    return asyncio.run(_fetch(limit))
