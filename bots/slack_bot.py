"""Slack bot (Socket Mode): drift alerts on every new message, commands on @mention.

python -m bots.slack_bot
"""

import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from bots.commands import HELP, handle
from config import settings
from connectors import seed_map
from connectors.slack import PersonLookup, to_event
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

        bus.publish("drift", status="drift", feature=result.get("feature"), ticket=result.get("ticket"), author=ev.author, text=ev.text[:160])
        thread = event.get("thread_ts") or event["ts"]
        hint = "Reply in this thread: `@Drift Monitor plan`, `fix it` or `keep the old scope`."
        say(text=f"{result['alert']}\n{hint}", thread_ts=thread)
        remember_thread(cid, thread, result["drift"]["requirement"])


def remember_thread(channel: str, thread_ts: str, requirement: str) -> None:
    """The alert thread is about one drift: store it on the Alert node so commands in the thread act on that drift."""
    from graph.db import get_graph

    # by the alert's own id (alert:<requirement>), which survives rebuilds; the FLAGS edge doesn't
    get_graph().query("MATCH (a:Alert {id: $a}) SET a.slack_thread = $t", {"a": f"alert:{requirement}", "t": f"{channel}:{thread_ts}"})


RECENT_ALERT_S = 30 * 60  # a command posted in the channel right after an alert means that alert


def thread_requirement(channel: str, thread_ts: str | None) -> str | None:
    """The drift a command is about: the alert whose thread it's in; or, posted in the channel instead of the thread,
    the most recent alert in this channel within RECENT_ALERT_S. Otherwise None (the command then asks which ticket)."""
    import time

    from graph.db import get_graph

    g = get_graph()
    if thread_ts:
        rows = g.query("MATCH (a:Alert {slack_thread: $t}) RETURN a.id LIMIT 1", {"t": f"{channel}:{thread_ts}"}).result_set
        if rows:
            return rows[0][0].removeprefix("alert:")
    rows = g.query(
        "MATCH (a:Alert) WHERE a.slack_thread STARTS WITH $c AND a.status = 'open' AND a.at_ms >= $since RETURN a.id ORDER BY a.at_ms DESC LIMIT 1",
        {"c": f"{channel}:", "since": int((time.time() - RECENT_ALERT_S) * 1000)},
    ).result_set
    return rows[0][0].removeprefix("alert:") if rows else None


@app.event("app_mention")
def on_mention(event, client, say):
    global _people
    text = event.get("text", "").split(">", 1)[-1]
    _people = _people or PersonLookup(client)
    try:
        actor = _people(event.get("user"))
        reply = handle(text, actor=actor, requirement=thread_requirement(event["channel"], event.get("thread_ts"))) or HELP
    except Exception as e:  # noqa: BLE001 - answer in the thread instead of going silent
        log.exception("command failed")
        reply = f"Sorry, that failed: {e}"
    say(text=reply[:39000], thread_ts=event.get("thread_ts") or event["ts"])


def main():
    logging.basicConfig(level=logging.INFO)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
