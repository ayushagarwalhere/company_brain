"""Contract tests for the Slack, Discord and GitHub connectors, with no tokens and no network.

The fakes return payloads shaped like the real APIs (cursor pagination, thread replies behind
conversations.replies, bot_message subtypes, GitHub page/per_page and rate-limit headers), so the
parsing, pagination, filtering and retry logic is exercised exactly as it would be against the services.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from connectors import discord as discord_conn
from connectors import github as gh
from connectors import scenario, seed_map
from connectors import slack as slack_conn

# ----------------------------------------------------------------------------- Slack


class FakeSlack:
    """Minimal Slack Web API: chat.postMessage, conversations.list/history/replies, users.info."""

    PAGE = 7  # small pages so pagination paths actually run

    def __init__(self, channels):
        self.channels = {name: f"C{i:03d}" for i, name in enumerate(channels)}
        self.msgs: dict[str, list[dict]] = {cid: [] for cid in self.channels.values()}
        self.users = {"U1": "maya.chen", "U2": "zara.qa"}
        self.clock = 1_790_000_000.0
        self.calls = {"history": 0, "replies": 0}

    def _page(self, items, cursor):
        start = int(cursor or 0)
        chunk = items[start : start + self.PAGE]
        nxt = start + self.PAGE if start + self.PAGE < len(items) else None
        return {"ok": True, "items": chunk, "response_metadata": {"next_cursor": str(nxt) if nxt else ""}}

    def conversations_list(self, types=None, limit=None, cursor=None):
        r = self._page([{"id": cid, "name": n} for n, cid in self.channels.items()], cursor)
        return {"channels": r["items"], "response_metadata": r["response_metadata"]}

    def chat_postMessage(self, channel, text, thread_ts=None, username=None, icon_emoji=None):
        self.clock += 1.5
        ts = f"{self.clock:.6f}"
        m = {"type": "message", "subtype": "bot_message", "bot_id": "B0BOT", "username": username, "text": text, "ts": ts}
        if thread_ts:
            m["thread_ts"] = thread_ts
            parent = next(x for x in self.msgs[channel] if x["ts"] == thread_ts)
            parent["thread_ts"] = thread_ts
            parent["reply_count"] = parent.get("reply_count", 0) + 1
        self.msgs[channel].append(m)
        return {"ok": True, "ts": ts, "channel": channel}

    def post_as_user(self, channel_name, user, text, thread_ts=None):
        cid = self.channels[channel_name]
        self.clock += 1.5
        m = {"type": "message", "user": user, "text": text, "ts": f"{self.clock:.6f}"}
        if thread_ts:
            m["thread_ts"] = thread_ts
            parent = next(x for x in self.msgs[cid] if x["ts"] == thread_ts)
            parent["thread_ts"] = thread_ts
            parent["reply_count"] = parent.get("reply_count", 0) + 1
        self.msgs[cid].append(m)
        return m

    def conversations_history(self, channel, limit=None, cursor=None):
        self.calls["history"] += 1
        top = [m for m in self.msgs[channel] if m.get("thread_ts") in (None, m["ts"])]
        r = self._page(sorted(top, key=lambda m: -float(m["ts"])), cursor)  # newest first, like Slack
        return {"messages": r["items"], "response_metadata": r["response_metadata"]}

    def conversations_replies(self, channel, ts, limit=None, cursor=None):
        self.calls["replies"] += 1
        thread = sorted([m for m in self.msgs[channel] if m["ts"] == ts or m.get("thread_ts") == ts], key=lambda m: float(m["ts"]))
        r = self._page(thread, cursor)
        return {"messages": r["items"], "response_metadata": r["response_metadata"]}

    def users_info(self, user):
        return {"user": {"id": user, "name": self.users.get(user, user)}}


@pytest.fixture
def tmp_seed_maps(monkeypatch):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="seedmaps-") as d:  # own temp dir: works where pytest's tmp root is locked
        monkeypatch.setattr(seed_map, "DIR", Path(d))
        yield Path(d)


def test_slack_seed_then_ingest_round_trip(monkeypatch, tmp_seed_maps):
    """Seeder posts the scenario into Slack; the connector reads it back with original ids, authors, times, threads."""
    import scripts.seed_slack as seeder

    fake = FakeSlack(["product", "engineering", "support-escalations", "random"])
    monkeypatch.setattr(seeder, "client", lambda: fake)
    monkeypatch.setattr(seeder.time, "sleep", lambda s: None)
    seeder.main()

    events = slack_conn.fetch_history(fake)
    expected = {m.id: m for m in scenario.messages() if m.source == "slack"}
    got = {e.id: e for e in events}
    assert set(got) == set(expected), (len(got), len(expected))
    for mid, exp in expected.items():
        e = got[mid]
        assert (e.author, e.ts, e.channel, e.thread_of, e.text) == (exp.author, exp.ts, exp.channel, exp.thread_of, exp.text), mid
    assert fake.calls["history"] > len(slack_conn.CHANNELS)  # pagination really happened


def test_slack_live_messages_and_own_alerts(monkeypatch, tmp_seed_maps):
    """A human posting live keeps its real id/author/time; our bot's own alert is not read back as a message."""
    fake = FakeSlack(["engineering"])
    root = fake.post_as_user("engineering", "U1", "Decision: exports go to 12 months now, BD-101")
    fake.post_as_user("engineering", "U2", "noted", thread_ts=root["ts"])
    fake.chat_postMessage(fake.channels["engineering"], ":warning: *Requirement drift on Ticket export*", thread_ts=root["ts"])
    events = slack_conn.fetch_history(fake)
    by_text = {e.text: e for e in events}
    assert set(by_text) == {"Decision: exports go to 12 months now, BD-101", "noted"}
    top, reply = by_text["Decision: exports go to 12 months now, BD-101"], by_text["noted"]
    assert top.author == "maya" and reply.author == "zara"  # handles mapped to people.json
    assert top.id == f"slack:{fake.channels['engineering']}:{root['ts']}" and reply.thread_of == top.id
    assert top.ts.endswith("Z") and top.url.startswith("https://slack.com/app_redirect")


# ----------------------------------------------------------------------------- Discord


def _dmsg(mid, content, author="maya_pm", bot=False, ref=None, channel="engineering"):
    return SimpleNamespace(
        id=mid,
        content=content,
        jump_url=f"https://discord.com/channels/1/2/{mid}",
        channel=SimpleNamespace(name=channel),
        created_at=datetime(2026, 10, 1, 7, 5, tzinfo=UTC),
        author=SimpleNamespace(name=author, display_name=author, bot=bot),
        reference=SimpleNamespace(message_id=ref) if ref else None,
    )


def test_discord_mapping_and_filters():
    people = discord_conn._people_by_name()
    smap = {"111": {"id": "m_sla_05", "author": "maya", "ts": "2026-09-17T05:31:00Z", "thread_of": "m_sla_03"}}
    seeded = _dmsg(111, "Agreed. Let's change it…", author="Maya Chen", bot=True)  # webhook-posted scenario message
    live = _dmsg(222, "Decision: warn 30 minutes before breach", author="devp")
    reply = _dmsg(333, "ok", author="zara_qa", ref=111)
    alert = _dmsg(444, "⚠️ Requirement drift on SLA", author="drift-bot", bot=True)  # our own alert
    assert [discord_conn.keep(m, smap) for m in (seeded, live, reply, alert)] == [True, True, True, False]
    e = discord_conn.to_event(seeded, smap, people)
    assert (e.id, e.author, e.ts, e.thread_of) == ("m_sla_05", "maya", "2026-09-17T05:31:00Z", "m_sla_03")
    e = discord_conn.to_event(live, smap, people)
    assert (e.id, e.author, e.ts) == ("discord:222", "dev", "2026-10-01T07:05:00Z")
    assert discord_conn.to_event(reply, smap, people).thread_of == "m_sla_05"  # reply to a seeded message


# ----------------------------------------------------------------------------- GitHub


class Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _pr(n, body="", merged=True, login="dakshhhhh-ops"):
    return {
        "number": n,
        "title": f"PR {n}",
        "body": body,
        "html_url": f"https://github.com/o/r/pull/{n}",
        "state": "closed",
        "merged_at": "2026-10-02T09:30:00Z" if merged else None,
        "created_at": "2026-10-02T07:00:00Z",
        "user": {"login": login},
    }


def test_github_pagination_trailers_and_rate_limit(monkeypatch):
    trailer = gh.trailer_block("sofia", "2026-09-24T10:00:00Z", "2026-09-25T05:44:00Z")
    page1 = [_pr(i) for i in range(1, 101)]
    page1[5] = _pr(6, "Fixes BD-101. Streams CSV." + trailer)
    page2 = [_pr(101, "Live PR, no trailer", merged=False)]
    calls, sleeps = [], []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["page"])
        if len(calls) == 1:  # first call hits the secondary rate limit
            return Resp(403, {"message": "rate limited"}, {"X-RateLimit-Remaining": "0", "Retry-After": "2"})
        return Resp(200, page1 if params["page"] == 1 else page2)

    monkeypatch.setattr(gh.requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    events = gh.pull_requests_from_api("o/r")
    assert calls == [1, 1, 2] and sleeps == [2.0]
    assert len(events) == 101
    e6 = next(e for e in events if e.extra["number"] == 6)
    assert (e6.author, e6.ts, e6.extra["merged_at"], e6.extra["body"]) == (
        "sofia",
        "2026-09-24T10:00:00Z",
        "2026-09-25T05:44:00Z",
        "Fixes BD-101. Streams CSV.",
    )
    assert e6.ticket_refs == ["BD-101"]
    live = events[-1]
    assert (live.author, live.extra["state"], live.extra["merged_at"]) == ("dakshhhhh-ops", "closed", None)


def test_github_gives_up_after_persistent_5xx(monkeypatch):
    monkeypatch.setattr(gh.requests, "get", lambda *a, **k: Resp(502))
    with pytest.raises(RuntimeError):
        gh.get_with_retry("https://api.github.com/x", attempts=3, sleep=lambda s: None)


def test_seed_maps_are_json_round_trippable(tmp_seed_maps):
    seed_map.save("slack", {"C1:1.0": {"id": "m1", "author": "maya", "ts": "2026-01-01T00:00:00Z", "thread_of": None}})
    assert json.loads((tmp_seed_maps / "slack.json").read_text(encoding="utf-8"))["C1:1.0"]["id"] == "m1"


# ----------------------------------------------------------------------------- live mode, end to end


def _falkordb_up():
    try:
        from graph.db import get_db

        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB not reachable")
def test_live_ingest_through_fake_apis_finds_the_planted_drift(monkeypatch, tmp_seed_maps):
    """`ingest(live=True)` reads Slack and GitHub through their (fake) APIs, then resolve() finds the planted drift."""
    import json as _json

    import scripts.seed_slack as seeder
    from benchmark.score_resolution import score
    from graph.db import get_graph
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    fake = FakeSlack(["product", "engineering", "support-escalations", "random"])
    monkeypatch.setattr(seeder, "client", lambda: fake)
    monkeypatch.setattr(seeder.time, "sleep", lambda s: None)
    seeder.main()
    monkeypatch.setattr(slack_conn, "client", lambda: fake)
    # Discord's gateway client can't be faked cheaply; its mapping is covered above, so feed its scenario events
    monkeypatch.setattr(discord_conn, "fetch_history", lambda limit=2000: [m for m in scenario.messages() if m.source == "discord"])
    prs = _json.loads(gh.SCENARIO_PRS.read_text(encoding="utf-8"))
    api_prs = [
        {
            "number": p["seq"],
            "title": p["title"],
            "html_url": f"https://github.com/o/r/pull/{p['seq']}",
            "body": p["body"] + gh.trailer_block(p["author"], p["created"], p.get("merged")),
            "state": "closed",
            "merged_at": "2026-10-16T00:00:00Z",
            "created_at": "2026-10-16T00:00:00Z",
            "user": {"login": "dakshhhhh-ops"},
        }
        for p in prs
    ]
    monkeypatch.setattr(gh.requests, "get", lambda url, params=None, headers=None, timeout=None: Resp(200, api_prs if params["page"] == 1 else []))

    name = "test_live_ingest"
    counts = ingest(live=True, reset=True, graph_name=name)
    g = get_graph(name)
    try:
        assert counts["nodes"]["Message"] == 300 and counts["nodes"]["PullRequest"] == 12
        resolve(g, "heuristic", log=lambda *_: None)
        s = score(g)
        assert s["drift_requirements"]["f1"] == 1.0 and s["drift_stale_prs"]["f1"] == 1.0, s["drift_requirements"]
    finally:
        g.delete()


def test_slack_code_formatting_is_stripped_from_message_text():
    """A message typed with Slack's code formatter arrives wrapped in ``` fences; the requirement text must not
    keep them (seen in the first real-workspace run)."""
    from connectors.slack import plain_text

    assert plain_text("```Decision: the export button must also offer a JSON download, BD-102.```") == (
        "Decision: the export button must also offer a JSON download, BD-102."
    )
    assert plain_text("use `csv` &amp; json") == "use csv & json"
