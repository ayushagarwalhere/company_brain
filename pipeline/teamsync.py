"""Keeps every connected team's graph current, the way the demo company's graph is.

What changes, and how it reaches the graph:
  * a new chat message          the Slack / Discord bot, at once (pipeline.live.process_message), with an in-thread alert
  * an edited / deleted message the bots (pipeline.live.edit_message / delete_message), then a re-resolve
  * people: joins, titles, roles the Slack directory on every pass (and Slack's user_change / team_join events),
                                Discord member updates; pipeline.identity keeps one Person per human
  * tickets, comments, PRs      GitHub, every pass, incrementally (connectors.github_work: only what changed since the
                                last pass; a changed issue body becomes the ticket's next version)
  * history                     when channels are picked, their recent history is imported once (import_slack_history)
After a pass that changed anything, resolve() re-derives features, requirement versions, supersession, IMPLEMENTS and
drift for that team's graph; human actions (write-backs, dismissals, follow-up tasks) are kept, as in a rebuild.

sync_team(org) is one pass; start() runs a pass over every team every TEAM_SYNC_SECONDS (default 300) inside the API
process. Status (when, what changed, errors) is stored per team and shown on the team's Setup page.
"""

import logging
import os
import threading
import time
from datetime import UTC, datetime

from connectors import installs

log = logging.getLogger("teamsync")
_running: set[str] = set()
_guard = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _after(iso: str | None) -> str | None:
    """One second after the newest update seen: GitHub's `since` is inclusive, so the next pass doesn't re-read it."""
    from datetime import timedelta

    if not iso:
        return iso
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extractor_name() -> str:
    from pipeline import llm

    return "llm" if llm.available() else "heuristic"


def _slack_client(token: str):
    from slack_sdk import WebClient
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    c = WebClient(token=token)
    c.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    return c


def reresolve(g) -> dict:
    """Re-derives everything resolve() owns for this graph and clears the dirty flag."""
    from pipeline.build import mark_build
    from pipeline.resolve import resolve

    name = _extractor_name()
    out = resolve(g, name, log=lambda *_: None, ungrouped_features=True)
    mark_build(g, name, live=True, llm_errors=out["llm_errors"], classified=len(out["classification"]))
    g.query("MERGE (s:SyncState {id: 'resolve'}) SET s.dirty = false, s.at = $at", {"at": _now()})
    return {"features": len(out["features"]), "chat_changes": len(out["changes"]), "implements": len(out["implements"])}


def _run_source(name: str, g, conf: dict, since: str | None, fakes: dict) -> dict:
    """One work source's pass: GitHub (issues, comments, PRs), Jira or Linear (tickets, comments)."""
    if name == "github":
        from connectors import github_work

        return github_work.sync(g, conf["repo"], conf.get("token"), since, people=fakes.get("github_people"))
    if name == "jira":
        from connectors import jira

        return jira.sync(g, conf["site"], conf["email"], conf["token"], conf["project"], since, history=fakes.get("jira_history"))
    from connectors import linear

    return linear.sync(g, conf["token"], conf["team"], since, query=fakes.get("linear_query"))


# a source is configured once its key field is saved
SOURCES = {"github": "repo", "jira": "project", "linear": "team"}


def sync_team(org: str, full: bool = False, github_people=None, **fakes) -> dict:
    """One pass for one team: people, then each connected work source (GitHub, Jira, Linear), then a re-resolve if
    anything changed. Never raises: errors are recorded in the team's status. `github_people` and `fakes` stand in for
    the remote APIs in tests."""
    from graph import writer
    from graph.db import _org, get_graph, set_org

    with _guard:
        if org in _running:
            return {"org": org, "skipped": "a pass is already running"}
        _running.add(org)
    token = set_org(org)
    status: dict = {"at": _now(), "errors": []}
    try:
        g = get_graph()
        writer.apply_schema(g)
        changed = full
        slack = installs.team_slack(org)
        if slack:
            try:
                from connectors.slack import sync_directory

                status["people_from_slack"] = sync_directory(g, _slack_client(slack["bot_token"]))
            except Exception as e:  # noqa: BLE001
                status["errors"].append(f"slack directory: {e}"[:200])
        settings = installs.team(org)
        for name, key in SOURCES.items():
            conf = settings.get(name) or {}
            if not conf.get(key):
                continue
            try:
                out = _run_source(name, g, conf, None if full else conf.get("since"), {"github_people": github_people, **fakes})
                installs.set_team(org, **{name: {"since": _after(out["until"])}})
                status[name] = {k: out[k] for k in ("tickets", "new_versions", "comments", "prs", "people")}
                changed = changed or any(out[k] for k in ("tickets", "comments", "prs"))
            except Exception as e:  # noqa: BLE001
                status["errors"].append(f"{name}: {e}"[:200])
        dirty = g.query("MATCH (s:SyncState {id: 'resolve'}) RETURN s.dirty").result_set
        if changed or (dirty and dirty[0][0]):
            try:
                status["resolved"] = reresolve(g)
            except Exception as e:  # noqa: BLE001
                status["errors"].append(f"resolve: {e}"[:200])
        from graph import queries as Q

        status["graph"] = {r["l"]: r["n"] for r in Q.rows(g, "MATCH (n) RETURN labels(n)[0] AS l, count(*) AS n")}
        status["open_drift"] = len(Q.drift(g)) if status["graph"].get("Feature") else 0
    except Exception as e:  # noqa: BLE001
        status["errors"].append(str(e)[:200])
    finally:
        _org.reset(token)
        with _guard:
            _running.discard(org)
    installs.set_team(org, status=status)
    return {"org": org, **status}


def import_slack_history(org: str, channels: list[dict], days: int = 90, limit: int = 2000) -> dict:
    """The picked channels' recent history, once: messages, threads and their authors, then a re-resolve."""
    from connectors.slack import TeamPeople, fetch_channels
    from graph import writer
    from graph.db import _org, get_graph, set_org

    slack = installs.team_slack(org)
    if not slack:
        return {"imported": 0}
    token = set_org(org)
    try:
        g = get_graph()
        writer.apply_schema(g)
        c = _slack_client(slack["bot_token"])
        events = fetch_channels(c, channels, TeamPeople(c), oldest=time.time() - days * 86400, limit=limit)
        if events:
            writer.write_messages(g, events)
        g.query("MERGE (s:SyncState {id: 'resolve'}) SET s.dirty = true")
        installs.set_team(org, status={"history": {"messages": len(events), "channels": [c["name"] for c in channels], "at": _now()}})
    finally:
        _org.reset(token)
    return {"imported": len(events), **sync_team(org)}


def in_background(fn, *args, **kwargs) -> None:
    threading.Thread(target=lambda: _safe(fn, *args, **kwargs), daemon=True).start()


def _safe(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        log.exception("team sync step failed")


def start(stop: threading.Event) -> threading.Thread | None:
    """A pass over every connected team every TEAM_SYNC_SECONDS (0 = off). Not under pytest."""
    every = int(os.getenv("TEAM_SYNC_SECONDS", "300") or 0)
    if every <= 0 or os.getenv("PYTEST_CURRENT_TEST"):
        return None

    def loop():
        while not stop.wait(every):
            for org in installs.team_orgs():
                _safe(sync_team, org)

    t = threading.Thread(target=loop, name="teamsync", daemon=True)
    t.start()
    return t
