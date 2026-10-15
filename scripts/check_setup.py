"""Phase 0 smoke test: verifies every external service the project depends on.

Run from the repo root:  python -m scripts.check_setup
Each check is independent, so one missing credential does not hide the others.
"""
import asyncio
import sys
import traceback

import requests

from config import settings

results: list[tuple[str, bool, str]] = []


def check(name):
    def wrap(fn):
        def run():
            try:
                detail = fn()
                results.append((name, True, detail or ""))
            except Exception as e:  # noqa: BLE001 - report every failure, keep going
                results.append((name, False, f"{type(e).__name__}: {e}"))
                if "-v" in sys.argv:
                    traceback.print_exc()
        return run
    return wrap


@check("FalkorDB")
def falkordb():
    if not settings.falkordb_password and settings.falkordb_host == "localhost":
        raise RuntimeError("FALKORDB_HOST / FALKORDB_PASSWORD not set")
    from graph.db import get_graph

    g = get_graph("_setup_check")
    g.query("MERGE (n:Ping {id: 1}) SET n.at = timestamp()")
    count = g.query("MATCH (n:Ping) RETURN count(n)").result_set[0][0]
    g.delete()
    return f"read/write OK ({count} test node)"


@check("Slack")
def slack():
    if not settings.slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN not set")
    from slack_sdk import WebClient

    client = WebClient(token=settings.slack_bot_token)
    auth = client.auth_test()
    detail = f"bot '{auth['user']}' in workspace '{auth['team']}'"
    if settings.slack_test_channel_id:
        hist = client.conversations_history(channel=settings.slack_test_channel_id, limit=1)
        msgs = hist.get("messages", [])
        detail += f"; read {len(msgs)} message(s) from test channel"
    if not settings.slack_app_token.startswith("xapp-"):
        detail += "; WARNING: SLACK_APP_TOKEN (xapp-) missing, Socket Mode will not work"
    return detail


@check("Discord")
def discord_check():
    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    out: dict = {}

    @client.event
    async def on_ready():
        try:
            guilds = client.guilds
            out["guilds"] = [g.name for g in guilds]
            target = next((g for g in guilds if str(g.id) == settings.discord_guild_id), None)
            if target:
                chan = next((c for c in target.text_channels
                             if c.permissions_for(target.me).read_message_history), None)
                if chan:
                    msgs = [m async for m in chan.history(limit=1)]
                    out["read"] = f"#{chan.name}: {len(msgs)} message(s)"
        finally:
            await client.close()

    asyncio.run(asyncio.wait_for(client.start(settings.discord_bot_token), timeout=30))
    detail = f"logged in as bot, guilds={out.get('guilds')}"
    if "read" in out:
        detail += f"; read {out['read']}"
    elif settings.discord_guild_id:
        detail += "; WARNING: could not read from DISCORD_GUILD_ID (bot invited? intent on?)"
    return detail


@check("GitHub")
def github():
    if not settings.github_repo or "/" not in settings.github_repo or settings.github_repo == "owner/repo":
        raise RuntimeError("GITHUB_REPO not set (expected owner/repo)")
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    r = requests.get(f"https://api.github.com/repos/{settings.github_repo}", headers=headers, timeout=15)
    r.raise_for_status()
    repo = r.json()
    if repo.get("private"):
        raise RuntimeError("repo is private; hackathon data must be public")
    remaining = r.headers.get("X-RateLimit-Remaining")
    return f"{repo['full_name']} (public), rate limit remaining={remaining}"


@check("DeepSeek")
def deepseek():
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    from openai import OpenAI

    client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    resp = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        max_tokens=5,
    )
    return f"{settings.deepseek_model} replied '{resp.choices[0].message.content.strip()}'"


if __name__ == "__main__":
    for fn in (falkordb, slack, discord_check, github, deepseek):
        fn()
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
