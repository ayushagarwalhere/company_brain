"""Discord bot: drift alerts on every new message, `!brain <command>` for commands.

python -m bots.discord_bot
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


@client.event
async def on_ready():
    log.info("logged in as %s", client.user)


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.webhook_id or not msg.content:
        return
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
