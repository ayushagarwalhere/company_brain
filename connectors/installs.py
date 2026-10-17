"""Where connected chat workspaces are kept: Slack workspaces installed through "Add to Slack" (with their bot token)
and the Discord servers the bot has been added to.

A JSON file outside git (INSTALLS_PATH, default data/installs.json). Tokens never leave this module except to the
bots; status() is what the website sees and has no secrets. In production this belongs in a secret store.
"""

import json
import os
import threading
import time
from pathlib import Path

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.getenv("INSTALLS_PATH") or Path(__file__).resolve().parent.parent / "data" / "installs.json")


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"slack": {}, "discord": {}}
    data = json.loads(p.read_text(encoding="utf-8") or "{}")
    return {"slack": data.get("slack", {}), "discord": data.get("discord", {})}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def save_slack(team_id: str, team: str, bot_token: str, bot_user_id: str | None, org: str | None = None) -> None:
    with _lock:
        data = _load()
        old = data["slack"].get(team_id, {})
        data["slack"][team_id] = {
            "team_id": team_id, "team": team, "bot_token": bot_token, "bot_user_id": bot_user_id,
            "org": org, "channels": old.get("channels", []), "installed_at": int(time.time()),
        }  # fmt: skip
        _save(data)


def slack_install(team_id: str | None) -> dict | None:
    return _load()["slack"].get(team_id or "")


def set_slack_channels(team_id: str, channels: list[dict]) -> None:
    with _lock:
        data = _load()
        if team_id in data["slack"]:
            data["slack"][team_id]["channels"] = channels
            _save(data)


def save_discord_guilds(guilds: list[dict]) -> None:
    """The servers the Discord bot is in right now (written by the bot when it starts and when it joins one)."""
    with _lock:
        data = _load()
        data["discord"] = {str(g["id"]): {"id": str(g["id"]), "name": g["name"], "seen_at": int(time.time())} for g in guilds}
        _save(data)


def status() -> dict:
    """What is connected, without any token."""
    data = _load()
    return {
        "slack": [{k: v for k, v in i.items() if k not in ("bot_token",)} for i in data["slack"].values()],
        "discord": list(data["discord"].values()),
    }
