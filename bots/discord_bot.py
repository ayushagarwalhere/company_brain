"""Discord bot: drift alerts on every new message, `!brain <command>` for commands.

python -m bots.discord_bot

One bot serves every server it is added to. The home server (DISCORD_GUILD_ID, the demo company) uses the default
graph; every other server gets its own graph (connectors/installs.py), so teams never see or feed each other's data.
"""

import asyncio
import logging

import discord

from bots.commands import HELP, handle
from config import settings
from connectors import seed_map
from connectors.discord import _people_by_name, to_event
from pipeline.live import process_message

log = logging.getLogger("discord_bot")
PREFIX = "!brain"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def send_long(channel_or_msg, text: str, reply: bool = False):
    chunks = [text[i : i + 1900] for i in range(0, len(text), 1900)] or ["(empty)"]
    for i, c in enumerate(chunks):
        if reply and i == 0:
            await channel_or_msg.reply(c, mention_author=False)
        else:
            target = channel_or_msg.channel if reply else channel_or_msg
            await target.send(c)


def record_servers() -> None:
    """The servers the bot is in: what the website shows as connected (connectors/installs.py)."""
    from connectors.installs import save_discord_guilds

    save_discord_guilds([{"id": g.id, "name": g.name} for g in client.guilds])


def welcome_channel(guild):
    """Where to say hello: the server's system channel, else the first text channel the bot may post in."""
    me = guild.me
    for ch in [guild.system_channel, *guild.text_channels]:
        if ch is not None and ch.permissions_for(me).send_messages:
            return ch
    return None


@client.event
async def on_ready():
    log.info("logged in as %s, in %d servers", client.user, len(client.guilds))
    record_servers()


@client.event
async def on_guild_join(guild):
    import os

    from api.integrations import welcome
    from connectors.installs import discord_org

    log.info("added to %s", guild.name)
    org = discord_org(guild.id, guild.name)  # its own graph, created now
    record_servers()
    ch = welcome_channel(guild)
    if org and ch:
        await send_long(ch, welcome("discord", org, (os.getenv("PUBLIC_URL") or "").rstrip("/")))


@client.event
async def on_guild_remove(guild):
    record_servers()


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.webhook_id or not msg.content or msg.guild is None:
        return  # bots, webhooks, empty messages and DMs
    from connectors.installs import discord_org
    from graph.db import _org, set_org

    token = set_org(discord_org(msg.guild.id, msg.guild.name))  # this server's graph, for everything below
    try:
        await _on_message(msg)
    finally:
        _org.reset(token)


async def _on_message(msg: discord.Message):
    if msg.content.startswith(PREFIX):
        text = msg.content[len(PREFIX) :]
        try:
            people = _people_by_name()
            actor = people.get(msg.author.name, people.get(getattr(msg.author, "display_name", ""), f"discord:{msg.author.name}"))
            reply = await asyncio.to_thread(handle, text, actor)
        except Exception as e:  # noqa: BLE001 - answer instead of going silent
            log.exception("command failed")
            reply = f"Sorry, that failed: {e}"
        await send_long(msg, reply or HELP, reply=True)
        return
    ev = to_event(msg, seed_map.load("discord"), _people_by_name())
    try:
        result = await asyncio.to_thread(process_message, ev)
    except Exception:  # noqa: BLE001 - keep the bot alive
        log.exception("drift check failed")
        return
    log.info("%s -> %s", ev.id, result.get("status"))
    if result.get("status") == "drift":
        from api import bus  # cross-process: shows up live on every open dashboard

        bus.publish("drift", status="drift", feature=result.get("feature"), ticket=result.get("ticket"), author=ev.author, text=ev.text[:160])
        await send_long(msg, result["alert"].replace(":warning:", "⚠️"), reply=True)


def main():
    logging.basicConfig(level=logging.INFO)
    client.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()
