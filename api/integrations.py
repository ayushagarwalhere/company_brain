"""Connect Slack and Discord from the website.

Slack, "Add to Slack": GET /api/connect/slack sends the person to Slack's OAuth v2 consent page. Slack sends them back
to /api/connect/slack/callback with a code, exchanged here for the workspace's bot token (oauth.v2.access) and stored
(connectors/installs.py). The website then lists the workspace's public channels; the ones picked are joined
(conversations.join), and the Slack bot (bots/slack_bot.py, Socket Mode) answers in every installed workspace.
  Needs SLACK_CLIENT_ID and SLACK_CLIENT_SECRET (Slack app > Basic Information), and <PUBLIC_URL>/api/connect/slack/callback
  under OAuth & Permissions > Redirect URLs (Slack wants HTTPS there: the deployed site, or a tunnel locally).

Discord, "Add to Discord": GET /api/connect/discord sends the person to Discord's page for adding the bot to a server
(DISCORD_CLIENT_ID, or the application id inside DISCORD_BOT_TOKEN). One bot token serves every server; the running
bot (bots/discord_bot.py) records the servers it is in, which is what the website shows as connected.
"""

import base64
import hashlib
import hmac
import os
import time
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from connectors import installs

router = APIRouter()

SLACK_SCOPES = ["channels:read", "channels:history", "channels:join", "chat:write", "users:read", "app_mentions:read"]
# View Channels, Send Messages, Read Message History, Manage Webhooks (seeding), Send Messages in Threads
DISCORD_PERMISSIONS = 1024 | 2048 | 65536 | 536870912 | 274877906944
STATE_MAX_AGE_S = 900


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _auth(authorization: str | None = Header(default=None), x_ingest_token: str | None = Header(default=None)):
    from api.main import require_ingest_token

    return require_ingest_token(authorization, x_ingest_token)


def discord_client_id() -> str:
    """DISCORD_CLIENT_ID, or the application id inside the bot token (its first part is the bot user's id in base64,
    which for a bot is the application's id)."""
    if _env("DISCORD_CLIENT_ID"):
        return _env("DISCORD_CLIENT_ID")
    first = _env("DISCORD_BOT_TOKEN").split(".")[0]
    try:
        out = base64.b64decode(first + "=" * (-len(first) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return ""
    return out if out.isdigit() else ""


def _slack_ready() -> bool:
    return bool(_env("SLACK_CLIENT_ID") and _env("SLACK_CLIENT_SECRET"))


def _base(request: Request) -> str:
    return (_env("PUBLIC_URL") or str(request.base_url)).rstrip("/")


def _sign(ts: str, org: str) -> str:
    return hmac.new(_env("SLACK_CLIENT_SECRET").encode(), f"{ts}.{org}".encode(), hashlib.sha256).hexdigest()[:32]


def make_state(org: str = "") -> str:
    """Signed, short-lived: proves the callback answers a consent page this server opened (CSRF), and carries the org."""
    ts = str(int(time.time()))
    return f"{ts}.{org}.{_sign(ts, org)}"


def check_state(state: str) -> str:
    try:
        ts, org, sig = state.split(".", 2)
        fresh = time.time() - int(ts) <= STATE_MAX_AGE_S
    except ValueError:
        raise HTTPException(400, "bad state") from None
    if not fresh or not hmac.compare_digest(sig, _sign(ts, org)):
        raise HTTPException(400, "expired or forged state")
    return org


@router.get("/api/integrations")
def integrations():
    """What can be connected and what is: no tokens, ever."""
    st = installs.status()
    return {
        "slack": {
            "ready": _slack_ready(),
            "bot_from_env": bool(_env("SLACK_BOT_TOKEN") and _env("SLACK_APP_TOKEN")),
            "workspaces": st["slack"],
            "scopes": SLACK_SCOPES,
        },
        "discord": {"ready": bool(discord_client_id()), "bot_token_set": bool(_env("DISCORD_BOT_TOKEN")), "servers": st["discord"]},
    }


@router.get("/api/connect/slack")
def connect_slack(request: Request, org: str = ""):
    if not _slack_ready():
        return RedirectResponse("/?connect=slack&error=not_configured", 302)
    q = urlencode(
        {
            "client_id": _env("SLACK_CLIENT_ID"),
            "scope": ",".join(SLACK_SCOPES),
            "redirect_uri": f"{_base(request)}/api/connect/slack/callback",
            "state": make_state(org),
        }
    )
    return RedirectResponse(f"https://slack.com/oauth/v2/authorize?{q}", 302)


@router.get("/api/connect/slack/callback")
def slack_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:  # the person pressed Cancel on Slack's page
        return RedirectResponse(f"/?connect=slack&error={quote(error)}", 302)
    org = check_state(state)
    r = requests.post(
        "https://slack.com/api/oauth.v2.access",
        data={
            "client_id": _env("SLACK_CLIENT_ID"),
            "client_secret": _env("SLACK_CLIENT_SECRET"),
            "code": code,
            "redirect_uri": f"{_base(request)}/api/connect/slack/callback",
        },
        timeout=15,
    ).json()
    if not r.get("ok"):
        return RedirectResponse(f"/?connect=slack&error={quote(r.get('error') or 'oauth_failed')}", 302)
    team = r.get("team") or {}
    installs.save_slack(team.get("id", ""), team.get("name", ""), r["access_token"], r.get("bot_user_id"), org or None)
    return RedirectResponse(f"/?connected=slack&team={quote(team.get('id', ''))}", 302)


def _slack_client(team: str):
    from slack_sdk import WebClient

    inst = installs.slack_install(team)
    if not inst:
        raise HTTPException(404, "workspace not connected")
    return inst, WebClient(token=inst["bot_token"])


@router.get("/api/connect/slack/channels")
def slack_channels(team: str):
    """The workspace's public channels, and which ones the bot watches."""
    inst, c = _slack_client(team)
    chans = c.conversations_list(types="public_channel", exclude_archived=True, limit=200)["channels"]
    watched = {x["id"] for x in inst.get("channels", [])}
    return {
        "team": inst["team"],
        "channels": [
            {"id": ch["id"], "name": ch["name"], "members": ch.get("num_members"), "watched": ch["id"] in watched or bool(ch.get("is_member"))}
            for ch in sorted(chans, key=lambda ch: ch["name"])
        ],
    }


class WatchIn(BaseModel):
    team: str
    channels: list[str]


@router.post("/api/connect/slack/channels", dependencies=[Depends(_auth)])
def slack_watch(body: WatchIn):
    """Joins the picked channels, so the bot receives their messages."""
    inst, c = _slack_client(body.team)
    joined, failed = [], []
    for cid in body.channels:
        try:
            ch = c.conversations_join(channel=cid)["channel"]
            joined.append({"id": ch["id"], "name": ch["name"]})
        except Exception as e:  # noqa: BLE001 - report per channel
            failed.append({"id": cid, "error": str(e)[:120]})
    installs.set_slack_channels(body.team, joined)
    return {"team": inst["team"], "joined": joined, "failed": failed}


@router.get("/api/connect/discord")
def connect_discord():
    cid = discord_client_id()
    if not cid:
        return RedirectResponse("/?connect=discord&error=not_configured", 302)
    q = urlencode({"client_id": cid, "scope": "bot", "permissions": DISCORD_PERMISSIONS})
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{q}", 302)
