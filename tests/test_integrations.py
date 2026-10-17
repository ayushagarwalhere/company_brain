"""Connecting Slack and Discord from the website: the buttons' redirects, the OAuth callback (state check, token
exchange, stored install), channel picking, and isolation: every team that connects gets its own graph, the public
site only counts connections, and no token or org id ever reaches the browser."""

import base64
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from graph import db


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.TemporaryDirectory()  # not pytest's tmp_path: its base dir isn't always readable on Windows
    monkeypatch.setenv("INSTALLS_PATH", str(Path(tmp.name) / "installs.json"))
    for k in (
        "SLACK_CLIENT_ID",
        "SLACK_CLIENT_SECRET",
        "DISCORD_CLIENT_ID",
        "DISCORD_BOT_TOKEN",
        "DISCORD_GUILD_ID",
        "PUBLIC_URL",
        "SLACK_BOT_TOKEN",
        "INGEST_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)
    from api.main import app

    yield TestClient(app, follow_redirects=False)
    tmp.cleanup()


@pytest.fixture()
def slack_app(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "s3cret")


def _install(client, monkeypatch, team="T1", name="Acme", home=None):
    from api import integrations

    monkeypatch.setattr(integrations, "home_slack_team", lambda: home)

    class Resp:
        @staticmethod
        def json():
            return {"ok": True, "access_token": "xoxb-secret", "bot_user_id": "UBOT", "team": {"id": team, "name": name}}

    sent = {}

    def fake_post(url, data, timeout):
        sent.update(url=url, **data)
        return Resp()

    monkeypatch.setattr(integrations.requests, "post", fake_post)
    r = client.get(f"/api/connect/slack/callback?code=the-code&state={integrations.make_state()}")
    loc = urlparse(r.headers["location"])
    return parse_qs(loc.query), sent


def test_buttons_explain_what_is_missing_when_the_server_is_not_set_up(client):
    st = client.get("/api/integrations").json()
    assert st["slack"]["ready"] is False and st["discord"]["ready"] is False
    assert client.get("/api/connect/slack").headers["location"] == "/?connect=slack&error=not_configured"
    assert client.get("/api/connect/discord").headers["location"] == "/?connect=discord&error=not_configured"


def test_add_to_slack_goes_to_slacks_consent_page(client, slack_app, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://brain.example.com")
    loc = urlparse(client.get("/api/connect/slack").headers["location"])
    q = parse_qs(loc.query)
    assert (loc.netloc, loc.path) == ("slack.com", "/oauth/v2/authorize")
    assert q["client_id"] == ["123.456"] and q["redirect_uri"] == ["https://brain.example.com/api/connect/slack/callback"]
    assert {"channels:history", "chat:write", "channels:join"} <= set(q["scope"][0].split(","))
    assert q["state"][0]


def test_slack_install_gets_its_own_graph_and_the_site_never_sees_token_or_org(client, slack_app, monkeypatch):
    from connectors import installs

    assert client.get("/api/connect/slack/callback?code=x&state=1.forged").status_code == 400  # CSRF: not our state
    q, sent = _install(client, monkeypatch)
    assert q["connected"] == ["slack"] and q["team"] == ["T1"] and q["key"][0]
    assert sent["url"].endswith("oauth.v2.access") and sent["code"] == "the-code" and sent["client_secret"] == "s3cret"
    inst = installs.slack_install("T1")
    assert inst["bot_token"] == "xoxb-secret" and inst["org"].startswith("slack-")  # a private graph of its own
    st = client.get("/api/integrations")
    assert st.json()["slack"]["workspaces"] == 1
    assert "xoxb-secret" not in st.text and inst["org"] not in st.text and "Acme" not in st.text
    q2, _ = _install(client, monkeypatch)  # reinstalling keeps the same graph
    assert installs.slack_install("T1")["org"] == inst["org"]
    assert client.get("/api/connect/slack/callback?error=access_denied").headers["location"] == "/?connect=slack&error=access_denied"


def test_the_home_workspace_stays_on_the_demo_graph(client, slack_app, monkeypatch):
    from connectors import installs

    _install(client, monkeypatch, team="THOME", name="Brightdesk", home="THOME")
    assert installs.slack_install("THOME")["org"] is None


def test_only_the_installer_picks_channels_and_a_new_team_gets_a_welcome(client, slack_app, monkeypatch):
    import slack_sdk

    from connectors import installs

    monkeypatch.setenv("PUBLIC_URL", "https://brain.example.com")
    q, _ = _install(client, monkeypatch)
    key = q["key"][0]
    joined, posted = [], []

    class FakeWeb:
        def __init__(self, token):
            assert token == "xoxb-secret"

        def conversations_join(self, channel):
            joined.append(channel)
            return {"channel": {"id": channel, "name": {"C1": "engineering", "C2": "product"}[channel]}}

        def chat_postMessage(self, channel, text):
            posted.append((channel, text))

    monkeypatch.setattr(slack_sdk, "WebClient", FakeWeb)
    assert client.post("/api/connect/slack/channels", json={"team": "T1", "channels": ["C1"]}).status_code == 403  # no key
    assert client.get("/api/connect/slack/channels?team=T1&key=1.bad").status_code == 403
    r = client.post("/api/connect/slack/channels", json={"team": "T1", "key": key, "channels": ["C1", "C2"]}).json()
    assert joined == ["C1", "C2"] and [c["name"] for c in r["joined"]] == ["engineering", "product"] and r["private_graph"]
    org = installs.slack_install("T1")["org"]
    assert len(posted) == 1 and posted[0][0] == "C1" and f"https://brain.example.com/?app&org={org}" in posted[0][1]
    client.post("/api/connect/slack/channels", json={"team": "T1", "key": key, "channels": ["C1"]})
    assert len(posted) == 1  # one welcome, not one per change


def test_discord_servers_get_their_own_graph_except_the_home_one(client, monkeypatch):
    from connectors import installs

    app_id = "1234567890123456789"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", base64.b64encode(app_id.encode()).decode().rstrip("=") + ".abc.def")
    monkeypatch.setenv("DISCORD_GUILD_ID", "100")
    q = parse_qs(urlparse(client.get("/api/connect/discord").headers["location"]).query)
    assert (q["client_id"], q["scope"]) == ([app_id], ["bot"]) and int(q["permissions"][0]) & 2048
    assert installs.discord_org(100, "Brightdesk") is None  # the demo company's server
    org = installs.discord_org(42, "Other team")
    assert org.startswith("discord-") and installs.discord_org(42) == org  # stable
    installs.save_discord_guilds([{"id": 42, "name": "Other team"}, {"id": 100, "name": "Brightdesk"}])
    assert installs.discord_org(42) == org  # recording servers keeps their graphs
    st = client.get("/api/integrations")
    assert st.json()["discord"]["servers"] == 2 and org not in st.text and "Other team" not in st.text


def test_a_team_graph_is_never_replaced_with_demo_data(client):
    assert client.post("/api/orgs/slack-0123456789/bootstrap").status_code == 403
    assert client.post("/api/demo/reset", headers={"X-Org": "discord-0123456789"}).status_code == 403


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
def test_a_teams_messages_land_in_its_own_graph_only():
    from graph.db import _org, get_graph, org_graph_name, set_org
    from pipeline import llm
    from pipeline.events import Event
    from pipeline.live import process_message

    org = "discord-test0isolation"
    ev = Event(source="discord", kind="message", id="discord:iso:1", author="discord:someone", ts="2026-10-18T10:00:00Z",
               text="Decision: our export must support 12 months, BD-101", channel="general")  # fmt: skip
    llm_was = llm.available
    llm.available = lambda ttl=300.0: False
    token = set_org(org)
    try:
        out = process_message(ev)
    finally:
        _org.reset(token)
        llm.available = llm_was
    try:
        assert out["status"] == "no-features"  # an empty graph of its own: nothing to compare against yet
        assert get_graph(org_graph_name(org)).query("MATCH (m:Message {id: 'discord:iso:1'}) RETURN count(m)").result_set[0][0] == 1
        default = db.settings.falkordb_graph
        if default in db.get_db().list_graphs():
            assert get_graph(default).query("MATCH (m:Message {id: 'discord:iso:1'}) RETURN count(m)").result_set[0][0] == 0
    finally:
        get_graph(org_graph_name(org)).delete()
