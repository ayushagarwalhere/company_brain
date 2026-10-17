"""Slack bot (Socket Mode): drift alerts on every new message, commands on @mention.

python -m bots.slack_bot

Serves every workspace that installed the app through "Add to Slack" on the website (api/integrations.py stores each
workspace's bot token), plus the workspace whose SLACK_BOT_TOKEN is in .env. A workspace installed for an org feeds
that org's graph; the others feed the default graph.
"""

import logging
from contextlib import contextmanager

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.authorization import AuthorizeResult

from bots.commands import HELP, handle
from config import settings
from connectors import installs, seed_map
from connectors.slack import PersonLookup, TeamPeople, to_event
from pipeline.live import process_message

log = logging.getLogger("slack_bot")


def authorize(enterprise_id, team_id, logger):
    """The bot token for the workspace an event came from: an "Add to Slack" install, else the one in .env."""
    inst = installs.slack_install(team_id)
    if inst:
        return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id, bot_token=inst["bot_token"], bot_user_id=inst.get("bot_user_id"))
    if settings.slack_bot_token:
        return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id, bot_token=settings.slack_bot_token)
    return None


app = App(authorize=authorize)
_people: dict[str, PersonLookup | TeamPeople] = {}
_channel_names: dict[str, str] = {}


@contextmanager
def org_of(team_id: str | None):
    """Run in the graph of the org this workspace was connected to (default graph when none)."""
    from graph.db import _org, set_org

    token = set_org((installs.slack_install(team_id) or {}).get("org"))
    try:
        yield
    finally:
        _org.reset(token)


def people_for(team_id: str | None, client) -> PersonLookup | TeamPeople:
    """Who wrote a message: the demo's hand-written people.json for the home workspace; for a connected team, its
    Slack directory through pipeline.identity (names, titles, one Person across Slack, Discord and GitHub)."""
    if (team_id or "") not in _people:
        team = (installs.slack_install(team_id) or {}).get("org")
        _people[team_id or ""] = TeamPeople(client) if team else PersonLookup(client)
    return _people[team_id or ""]


def channel_name(client, cid: str) -> str:
    if cid not in _channel_names:
        _channel_names[cid] = client.conversations_info(channel=cid)["channel"]["name"]
    return _channel_names[cid]


@app.event("message")
def on_message(event, client, say, context):
    sub = event.get("subtype")
    if sub in ("message_changed", "message_deleted"):
        with org_of(context.team_id):
            _on_change(event, client, context.team_id)
        return
    if event.get("bot_id") or sub:
        return  # ignore bots (including ourselves), joins and other system messages
    with org_of(context.team_id):
        _on_message(event, client, say, context.team_id)


def _on_change(event, client, team_id):
    """An edited message is checked again with its new text; a deleted one leaves the graph (pipeline.live)."""
    from pipeline.live import delete_message, edit_message

    cid = event["channel"]
    if event["subtype"] == "message_deleted":
        prev = event.get("previous_message") or {}
        delete_message(f"slack:{cid}:{prev.get('ts') or event.get('deleted_ts')}")
        return
    msg = event.get("message") or {}
    if msg.get("bot_id") or not msg.get("text") or (event.get("previous_message") or {}).get("text") == msg.get("text"):
        return  # a bot's edit, or only an unfurl/attachment changed
    try:
        edit_message(to_event(msg, channel_name(client, cid), cid, people_for(team_id, client), seed_map.load("slack")))
    except Exception:  # noqa: BLE001 - never crash the socket loop
        log.exception("edit failed")


@app.event("user_change")
@app.event("team_join")
def on_member(event, context):
    """Someone joined or changed their profile (name, title): their Person follows (connected teams only)."""
    if not (installs.slack_install(context.team_id) or {}).get("org"):
        return
    from connectors.slack import _slack_identity
    from graph.db import get_graph

    with org_of(context.team_id):
        u = event.get("user") or {}
        if u.get("id") and not u.get("is_bot") and not u.get("deleted"):
            _slack_identity(get_graph(), u)
            p = _people.get(context.team_id or "")
            if isinstance(p, TeamPeople):
                p.forget(u["id"])


def _on_message(event, client, say, team_id):
    cid = event["channel"]
    ev = to_event(event, channel_name(client, cid), cid, people_for(team_id, client), seed_map.load("slack"))
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
def on_mention(event, client, say, context):
    text = event.get("text", "").split(">", 1)[-1]
    try:
        actor = people_for(context.team_id, client)(event.get("user"))
        with org_of(context.team_id):
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
