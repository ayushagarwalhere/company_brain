"""Where connected chat workspaces are kept: Slack workspaces installed through "Add to Slack" (with their bot token)
and the Discord servers the bot has been added to.

Isolation: every workspace or server except the home one (the Slack workspace in SLACK_BOT_TOKEN, the Discord server
in DISCORD_GUILD_ID: the demo company) gets its own org, so its messages go into its own graph and never mix with the
demo or with another team's. The org id is random ("slack-3f9a1c7e2b"): with no sign-in yet, it is the only key to
that graph's dashboard, so it is shown only to that team (in the bot's welcome message) and never on the public site.

A JSON file outside git (INSTALLS_PATH, default data/installs.json). Tokens and org ids never leave this module except
to the bots and that team's own channel; status() is what the website sees. In production this belongs in a secret store.
"""

import json
import os
import secrets
import threading
import time
from pathlib import Path

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.getenv("INSTALLS_PATH") or Path(__file__).resolve().parent.parent / "data" / "installs.json")


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"slack": {}, "discord": {}, "teams": {}}
    data = json.loads(p.read_text(encoding="utf-8") or "{}")
    return {"slack": data.get("slack", {}), "discord": data.get("discord", {}), "teams": data.get("teams", {})}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def new_org(kind: str) -> str:
    return f"{kind}-{secrets.token_hex(5)}"


def is_team_org(org: str | None) -> bool:
    """A connected team's own graph (never to be replaced with demo data)."""
    return bool(org) and str(org).startswith(("slack-", "discord-"))


def save_slack(team_id: str, team: str, bot_token: str, bot_user_id: str | None, home: bool = False) -> dict:
    """Stores a workspace's install. A reinstall keeps its org (and so its graph); a new workspace gets a fresh org,
    unless it is the home workspace, which stays on the default graph."""
    with _lock:
        data = _load()
        old = data["slack"].get(team_id, {})
        org = None if home else old.get("org") or new_org("slack")
        data["slack"][team_id] = {
            "team_id": team_id, "team": team, "bot_token": bot_token, "bot_user_id": bot_user_id,
            "org": org, "channels": old.get("channels", []), "installed_at": int(time.time()),
        }  # fmt: skip
        _save(data)
        return data["slack"][team_id]


def slack_install(team_id: str | None) -> dict | None:
    return _load()["slack"].get(team_id or "")


def set_slack_channels(team_id: str, channels: list[dict]) -> None:
    with _lock:
        data = _load()
        if team_id in data["slack"]:
            data["slack"][team_id]["channels"] = channels
            _save(data)


def discord_org(guild_id, name: str = "") -> str | None:
    """The org of a Discord server: none (the default graph) for the home server, otherwise its own, created once."""
    gid = str(guild_id)
    if gid == (os.getenv("DISCORD_GUILD_ID") or "").strip():
        return None
    with _lock:
        data = _load()
        g = data["discord"].setdefault(gid, {"id": gid, "name": name})
        if not g.get("org"):
            g["org"] = new_org("discord")
            _save(data)
        return g["org"]


def save_discord_guilds(guilds: list[dict]) -> None:
    """The servers the Discord bot is in right now (written by the bot when it starts and when it joins one).
    A server's org survives: leaving and rejoining keeps its graph."""
    with _lock:
        data = _load()
        current = {str(g["id"]) for g in guilds}
        for g in guilds:
            rec = data["discord"].setdefault(str(g["id"]), {"id": str(g["id"])})
            rec.update(name=g["name"], seen_at=int(time.time()), active=True)
        for gid, rec in data["discord"].items():
            if gid not in current:
                rec["active"] = False
        _save(data)


def status() -> dict:
    """What the public website may show: how many teams are connected. No names, channels, org ids or tokens."""
    data = _load()
    return {
        "slack_workspaces": len(data["slack"]),
        "discord_servers": sum(1 for g in data["discord"].values() if g.get("active")),
    }


# ---------------------------------------------------------------- a connected team's own settings (by org)


def team(org: str) -> dict:
    """A team's settings and sync status: {"github": {"repo", "token", "since"}, "status": {...}}."""
    return _load()["teams"].get(org, {})


def set_team(org: str, **fields) -> dict:
    """Merges fields into a team's settings (a nested dict merges one level deep)."""
    with _lock:
        data = _load()
        t = data["teams"].setdefault(org, {})
        for k, v in fields.items():
            t[k] = {**t.get(k, {}), **v} if isinstance(v, dict) and isinstance(t.get(k), dict) else v
        _save(data)
        return t


def team_slack(org: str) -> dict | None:
    """The Slack install that feeds this org's graph (with its bot token), if any."""
    return next((i for i in _load()["slack"].values() if i.get("org") == org), None)


def team_orgs() -> list[str]:
    """Every connected team's org: from Slack installs, Discord servers and teams with settings."""
    data = _load()
    orgs = {i.get("org") for i in data["slack"].values()} | {g.get("org") for g in data["discord"].values()} | set(data["teams"])
    return sorted(o for o in orgs if o)


def public_team(org: str) -> dict:
    """What a team's own dashboard may show about its connections: never a token."""
    data = _load()
    slack = team_slack(org)
    discord = [g for g in data["discord"].values() if g.get("org") == org]
    t = data["teams"].get(org, {})
    gh = t.get("github") or {}
    return {
        "org": org,
        "slack": {"team": slack["team"], "channels": slack.get("channels", [])} if slack else None,
        "discord": {"server": discord[0]["name"]} if discord else None,
        "github": {"repo": gh["repo"], "token_set": bool(gh.get("token")), "since": gh.get("since")} if gh.get("repo") else None,
        "jira": {k: (t.get("jira") or {}).get(k) for k in ("site", "project", "email", "since")} if (t.get("jira") or {}).get("project") else None,
        "linear": {k: (t.get("linear") or {}).get(k) for k in ("team", "since")} if (t.get("linear") or {}).get("team") else None,
        "status": t.get("status", {}),
    }
