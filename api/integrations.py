"""Connect Slack and Discord from the website.

Slack, "Add to Slack": GET /api/connect/slack sends the person to Slack's OAuth v2 consent page. Slack sends them back
to /api/connect/slack/callback with a code, exchanged here for the workspace's bot token (oauth.v2.access) and stored
(connectors/installs.py). The person who installed then picks the channels to watch (a setup key in their redirect
link authorises that, for two hours); the picked channels are joined (conversations.join), and the bot posts one
welcome message. The Slack bot (bots/slack_bot.py, Socket Mode) answers in every installed workspace.
  Needs SLACK_CLIENT_ID and SLACK_CLIENT_SECRET (Slack app > Basic Information), and <PUBLIC_URL>/api/connect/slack/callback
  under OAuth & Permissions > Redirect URLs (Slack wants HTTPS there: the deployed site, or a tunnel locally).

Discord, "Add to Discord": GET /api/connect/discord sends the person to Discord's page for adding the bot to a server
(DISCORD_CLIENT_ID, or the application id inside DISCORD_BOT_TOKEN). One bot token serves every server; the bot
(bots/discord_bot.py) gives each new server its own graph and posts a welcome message there.

Isolation: every workspace or server except the home one gets its own graph (connectors/installs.py), so a team that
adds the bot never sees the demo company's data, never feeds it, and never sees another team's.
"""

import base64
import hashlib
import hmac
import os
import time
from functools import lru_cache
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from connectors import installs

router = APIRouter()

# users:read.email and usergroups:read let a team's people be matched across Slack and GitHub by email, and their Slack
# user groups decide document access (pipeline/identity.py)
SLACK_SCOPES = ["channels:read", "channels:history", "channels:join", "chat:write", "users:read", "users:read.email", "usergroups:read", "app_mentions:read"]
# View Channels, Send Messages, Read Message History, Manage Webhooks (seeding), Send Messages in Threads
DISCORD_PERMISSIONS = 1024 | 2048 | 65536 | 536870912 | 274877906944
STATE_MAX_AGE_S = 900
SETUP_MAX_AGE_S = 2 * 3600


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


def _sign(msg: str) -> str:
    return hmac.new(_env("SLACK_CLIENT_SECRET").encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def _signed(ts: str, msg: str, sig: str, max_age: int) -> bool:
    try:
        fresh = time.time() - int(ts) <= max_age
    except ValueError:
        return False
    return fresh and hmac.compare_digest(sig, _sign(msg))


def make_state() -> str:
    """Signed and short-lived: proves the callback answers a consent page this server opened (CSRF)."""
    ts = str(int(time.time()))
    return f"{ts}.{_sign(f'state.{ts}')}"


def check_state(state: str) -> None:
    ts, _, sig = state.partition(".")
    if not _signed(ts, f"state.{ts}", sig, STATE_MAX_AGE_S):
        raise HTTPException(400, "expired or forged state")


def setup_key(team: str) -> str:
    """Given only to the person who just installed (in their redirect link): lets them pick the channels for two hours."""
    ts = str(int(time.time()))
    return f"{ts}.{_sign(f'setup.{team}.{ts}')}"


def check_setup_key(team: str, key: str) -> None:
    ts, _, sig = (key or "").partition(".")
    if not _signed(ts, f"setup.{team}.{ts}", sig, SETUP_MAX_AGE_S):
        raise HTTPException(403, "this link has expired: add the app to Slack again to pick channels")


@lru_cache(maxsize=1)
def home_slack_team() -> str | None:
    """The workspace of SLACK_BOT_TOKEN (the demo company's): it stays on the default graph."""
    if not _env("SLACK_BOT_TOKEN"):
        return None
    try:
        r = requests.post("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {_env('SLACK_BOT_TOKEN')}"}, timeout=10).json()
    except requests.RequestException:
        return None
    return r.get("team_id") if r.get("ok") else None


def welcome(platform: str, org: str | None, base: str) -> str:
    """The bot's one message to a new team: what it does, that their graph is theirs, and what isn't self-serve yet."""
    cmd = "@Drift Monitor help" if platform == "slack" else "!brain help"
    dash = f"Your dashboard: {base}/?app&org={org} (keep this link inside your team: it opens your graph). " if base and org else ""
    return (
        "👋 Drift Monitor is connected. I read the channels I'm in and keep a private graph for this "
        f"{'workspace' if platform == 'slack' else 'server'}: nothing here mixes with any other team's data.\n"
        "I flag a decision made in chat that never reached the ticket or the code, so I also need your tickets and "
        "pull requests. Connecting those isn't self-serve yet: until then I can only track what's said here.\n"
        f"{dash}Commands: {cmd}"
    )


@router.get("/api/integrations")
def integrations():
    """What can be connected, and how many teams are: no names, channels, org ids or tokens."""
    st = installs.status()
    return {
        "slack": {
            "ready": _slack_ready(),
            "bot_from_env": bool(_env("SLACK_BOT_TOKEN") and _env("SLACK_APP_TOKEN")),
            "workspaces": st["slack_workspaces"],
            "scopes": SLACK_SCOPES,
        },
        "discord": {"ready": bool(discord_client_id()), "bot_token_set": bool(_env("DISCORD_BOT_TOKEN")), "servers": st["discord_servers"]},
    }


@router.get("/api/connect/slack")
def connect_slack(request: Request):
    if not _slack_ready():
        return RedirectResponse("/?connect=slack&error=not_configured", 302)
    q = urlencode(
        {
            "client_id": _env("SLACK_CLIENT_ID"),
            "scope": ",".join(SLACK_SCOPES),
            "redirect_uri": f"{_base(request)}/api/connect/slack/callback",
            "state": make_state(),
        }
    )
    return RedirectResponse(f"https://slack.com/oauth/v2/authorize?{q}", 302)


@router.get("/api/connect/slack/callback")
def slack_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:  # the person pressed Cancel on Slack's page
        return RedirectResponse(f"/?connect=slack&error={quote(error)}", 302)
    check_state(state)
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
    tid = team.get("id", "")
    installs.save_slack(tid, team.get("name", ""), r["access_token"], r.get("bot_user_id"), home=tid == home_slack_team())
    return RedirectResponse(f"/?connected=slack&team={quote(tid)}&key={quote(setup_key(tid))}", 302)


def _slack_client(team: str, key: str):
    from slack_sdk import WebClient

    check_setup_key(team, key)
    inst = installs.slack_install(team)
    if not inst:
        raise HTTPException(404, "workspace not connected")
    return inst, WebClient(token=inst["bot_token"])


@router.get("/api/connect/slack/channels")
def slack_channels(team: str, key: str = ""):
    """The workspace's public channels, and which ones the bot watches (only for the person who just installed)."""
    inst, c = _slack_client(team, key)
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
    key: str = ""
    channels: list[str]


@router.post("/api/connect/slack/channels", dependencies=[Depends(_auth)])
def slack_watch(body: WatchIn, request: Request):
    """Joins the picked channels, so the bot receives their messages; a new team gets one welcome message."""
    inst, c = _slack_client(body.team, body.key)
    joined, failed = [], []
    for cid in body.channels:
        try:
            ch = c.conversations_join(channel=cid)["channel"]
            joined.append({"id": ch["id"], "name": ch["name"]})
        except Exception as e:  # noqa: BLE001 - report per channel
            failed.append({"id": cid, "error": str(e)[:120]})
    first_time = not inst.get("channels")
    installs.set_slack_channels(body.team, joined)
    if joined and inst.get("org"):  # the picked channels' recent history, imported once in the background
        from pipeline import teamsync

        teamsync.in_background(teamsync.import_slack_history, inst["org"], joined)
    if joined and first_time and inst.get("org"):
        try:
            c.chat_postMessage(channel=joined[0]["id"], text=welcome("slack", inst["org"], _base(request)))
        except Exception:  # noqa: BLE001 - the channels are joined either way
            pass
    return {"team": inst["team"], "joined": joined, "failed": failed, "private_graph": bool(inst.get("org"))}


@router.get("/api/connect/discord")
def connect_discord():
    cid = discord_client_id()
    if not cid:
        return RedirectResponse("/?connect=discord&error=not_configured", 302)
    q = urlencode({"client_id": cid, "scope": "bot", "permissions": DISCORD_PERMISSIONS})
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{q}", 302)
