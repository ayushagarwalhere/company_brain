"""Connecting Slack and Discord from the website: the buttons' redirects, the OAuth callback (state check, token
exchange, stored install), channel picking, and that no token ever reaches the browser."""

import base64
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.TemporaryDirectory()  # not pytest's tmp_path: its base dir isn't always readable on Windows
    monkeypatch.setenv("INSTALLS_PATH", str(Path(tmp.name) / "installs.json"))
    for k in ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "DISCORD_CLIENT_ID", "DISCORD_BOT_TOKEN", "PUBLIC_URL", "SLACK_BOT_TOKEN", "INGEST_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    from api.main import app

    yield TestClient(app, follow_redirects=False)
    tmp.cleanup()


def test_buttons_explain_what_is_missing_when_the_server_is_not_set_up(client):
    st = client.get("/api/integrations").json()
    assert st["slack"]["ready"] is False and st["discord"]["ready"] is False
    assert client.get("/api/connect/slack").headers["location"] == "/?connect=slack&error=not_configured"
    assert client.get("/api/connect/discord").headers["location"] == "/?connect=discord&error=not_configured"


def test_add_to_slack_goes_to_slacks_consent_page(client, monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("PUBLIC_URL", "https://brain.example.com")
    loc = urlparse(client.get("/api/connect/slack").headers["location"])
    q = parse_qs(loc.query)
    assert (loc.netloc, loc.path) == ("slack.com", "/oauth/v2/authorize")
    assert q["client_id"] == ["123.456"] and q["redirect_uri"] == ["https://brain.example.com/api/connect/slack/callback"]
    assert {"channels:history", "chat:write", "channels:join"} <= set(q["scope"][0].split(","))
    assert q["state"][0]


def test_slack_callback_checks_state_exchanges_the_code_and_never_shows_the_token(client, monkeypatch):
    from api import integrations

    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "s3cret")
    assert client.get("/api/connect/slack/callback?code=x&state=1.x.forged").status_code == 400  # CSRF: not our state
    sent = {}

    class Resp:
        @staticmethod
        def json():
            return {"ok": True, "access_token": "xoxb-secret", "bot_user_id": "UBOT", "team": {"id": "T1", "name": "Acme"}}

    def fake_post(url, data, timeout):
        sent.update(url=url, **data)
        return Resp()

    monkeypatch.setattr(integrations.requests, "post", fake_post)
    r = client.get(f"/api/connect/slack/callback?code=the-code&state={integrations.make_state()}")
    assert r.headers["location"] == "/?connected=slack&team=T1"
    assert sent["url"].endswith("oauth.v2.access") and sent["code"] == "the-code" and sent["client_secret"] == "s3cret"
    st = client.get("/api/integrations")
    assert st.json()["slack"]["workspaces"][0]["team"] == "Acme" and "xoxb-secret" not in st.text
    from connectors import installs

    assert installs.slack_install("T1")["bot_token"] == "xoxb-secret"  # kept for the bot, server-side only
    # cancelled on Slack's page
    assert client.get("/api/connect/slack/callback?error=access_denied").headers["location"] == "/?connect=slack&error=access_denied"


def test_picked_channels_are_joined(client, monkeypatch):
    import slack_sdk

    from connectors import installs

    installs.save_slack("T1", "Acme", "xoxb-secret", "UBOT")
    joined = []

    class FakeWeb:
        def __init__(self, token):
            assert token == "xoxb-secret"

        def conversations_join(self, channel):
            joined.append(channel)
            return {"channel": {"id": channel, "name": {"C1": "engineering", "C2": "product"}[channel]}}

    monkeypatch.setattr(slack_sdk, "WebClient", FakeWeb)
    r = client.post("/api/connect/slack/channels", json={"team": "T1", "channels": ["C1", "C2"]}).json()
    assert joined == ["C1", "C2"] and [c["name"] for c in r["joined"]] == ["engineering", "product"]
    assert [c["name"] for c in installs.slack_install("T1")["channels"]] == ["engineering", "product"]
    assert client.post("/api/connect/slack/channels", json={"team": "T9", "channels": []}).status_code == 404


def test_add_to_discord_uses_the_app_id_inside_the_bot_token(client, monkeypatch):
    app_id = "1234567890123456789"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", base64.b64encode(app_id.encode()).decode().rstrip("=") + ".abc.def")
    loc = urlparse(client.get("/api/connect/discord").headers["location"])
    q = parse_qs(loc.query)
    assert (loc.netloc, q["client_id"], q["scope"]) == ("discord.com", [app_id], ["bot"])
    perms = int(q["permissions"][0])
    assert perms & 2048 and perms & 65536  # send messages, read history
    from connectors import installs

    installs.save_discord_guilds([{"id": 42, "name": "Brightdesk"}])
    assert client.get("/api/integrations").json()["discord"]["servers"][0]["name"] == "Brightdesk"
