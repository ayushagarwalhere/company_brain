"""Slack bot (Socket Mode): drift alerts on every new message, commands on @mention.

    python -m bots.slack_bot
"""
import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from bots.commands import HELP, handle
from config import settings
from connectors.slack import PersonLookup, to_event
from connectors import seed_map
from pipeline.live import process_message

log = logging.getLogger("slack_bot")
app = App(token=settings.slack_bot_token)
_people = None
_channel_names: dict[str, str] = {}


def channel_name(client, cid: str) -> str:
    if cid not in _channel_names:
        _channel_names[cid] = client.conversations_info(channel=cid)["channel"]["name"]
    return _channel_names[cid]


@app.event("message")
def on_message(event, client, say):
    global _people
    if event.get("bot_id") or event.get("subtype"):
        return  # ignore bots (including ourselves), edits, joins
    _people = _people or PersonLookup(client)
    cid = event["channel"]
    ev = to_event(event, channel_name(client, cid), cid, _people, seed_map.load("slack"))
    try:
        result = process_message(ev)
    except Exception:  # noqa: BLE001 - never crash the socket loop
        log.exception("drift check failed")
        return
    log.info("%s -> %s", ev.id, result.get("status"))
    if result.get("status") == "drift":
        from api import bus  # cross-process: shows up live on every open dashboard
        bus.publish("drift", status="drift", feature=result.get("feature"), ticket=result.get("ticket"),
                    author=ev.author, text=ev.text[:160])
        say(text=result["alert"], thread_ts=event.get("thread_ts") or event["ts"])


@app.event("app_mention")
def on_mention(event, say):
    text = event.get("text", "").split(">", 1)[-1]
    reply = handle(text) or HELP
    say(text=reply[:39000], thread_ts=event.get("thread_ts") or event["ts"])


def main():
    logging.basicConfig(level=logging.INFO)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
