"""Posts the scenario's Discord messages via per-channel webhooks (one per fictional author name).

    python -m scripts.seed_discord

Needs the bot to have Manage Webhooks in #engineering, #design and #random.
Re-running skips messages already posted.
"""
import asyncio
import json

import discord

from config import settings
from connectors import scenario, seed_map

HOOK_NAME = "brain-seed"


async def run():
    people = {p["id"]: p for p in scenario.people()}
    msgs = [m for m in json.loads((scenario.SCENARIO / "messages.json").read_text(encoding="utf-8")) if m["platform"] == "discord"]
    smap = seed_map.load("discord")
    done = {v["id"] for v in smap.values()}
    c = discord.Client(intents=discord.Intents.default())

    @c.event
    async def on_ready():
        try:
            guild = c.get_guild(int(settings.discord_guild_id))
            chans = {ch.name: ch for ch in guild.text_channels}
            missing = {m["channel"] for m in msgs} - set(chans)
            if missing:
                print(f"Create these channels first: {sorted(missing)}")
                return
            hooks = {}
            for name in {m["channel"] for m in msgs}:
                existing = [h for h in await chans[name].webhooks() if h.name == HOOK_NAME]
                hooks[name] = existing[0] if existing else await chans[name].create_webhook(name=HOOK_NAME)
            for i, m in enumerate(msgs):
                if m["id"] in done:
                    continue
                sent = await hooks[m["channel"]].send(m["text"], username=people[m["author"]]["name"], wait=True)
                smap[str(sent.id)] = {"id": m["id"], "author": m["author"], "ts": m["ts"], "thread_of": m.get("thread_of")}
                done.add(m["id"])
                if i % 10 == 0:
                    seed_map.save("discord", smap)
                    print(f"{len(done)}/{len(msgs)}")
            seed_map.save("discord", smap)
            print(f"done: {len(done)} discord messages")
        finally:
            await c.close()

    await c.start(settings.discord_bot_token)


if __name__ == "__main__":
    asyncio.run(run())
