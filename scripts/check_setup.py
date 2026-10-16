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
    from graph.db import get_graph  # a local container needs no password; Cloud needs host + password

    g = get_graph("_setup_check")
    g.query("MERGE (n:Ping {id: 1}) SET n.at = timestamp()")
    count = g.query("MATCH (n:Ping) RETURN count(n)").result_set[0][0]
    g.delete()
    return f"read/write OK ({count} test node)"


# Bot token scopes the code actually uses (see docs/REAL_RUN.md): what each one is for
SLACK_SCOPES = {
    "channels:read": "list public channels and look up channel names (connector, bot)",
    "channels:history": "read channel history and thread replies (connector, bot message events)",
    "users:read": "map Slack users to people (connector)",
    "chat:write": "post drift alerts (bot)",
    "chat:write.customize": "post as each fictional author when seeding (scripts/seed_slack)",
    "app_mentions:read": "answer @mentions (bot)",
}


@check("Slack")
def slack():
    """PASS only if the bot token works, has every scope the code uses, Socket Mode has an app token, and
    the bot can read the test channel. Each FAIL says what to change in the Slack app settings."""
    if not settings.slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN not set: OAuth & Permissions -> Install to Workspace -> copy the xoxb- token into .env")
    if not settings.slack_bot_token.startswith("xoxb-"):
        raise RuntimeError("SLACK_BOT_TOKEN must be the Bot User OAuth Token (xoxb-...), not a user or app token")
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    client = WebClient(token=settings.slack_bot_token)
    auth = client.auth_test()
    granted = set(filter(None, (auth.headers.get("x-oauth-scopes") or auth.headers.get("X-OAuth-Scopes") or "").split(",")))
    missing = [sc for sc in SLACK_SCOPES if sc not in granted]
    if missing:
        raise RuntimeError(
            "missing bot scopes: "
            + ", ".join(f"{sc} ({SLACK_SCOPES[sc]})" for sc in missing)
            + ". Add them under OAuth & Permissions -> Bot Token Scopes, then reinstall the app"
        )
    if not settings.slack_app_token.startswith("xapp-"):
        raise RuntimeError(
            "SLACK_APP_TOKEN (xapp-...) missing: Basic Information -> App-Level Tokens -> generate one " "with connections:write, and enable Socket Mode"
        )
    detail = f"bot '{auth['user']}' in workspace '{auth['team']}', all {len(SLACK_SCOPES)} scopes granted"
    if settings.slack_test_channel_id:
        try:
            hist = client.conversations_history(channel=settings.slack_test_channel_id, limit=1)
        except SlackApiError as e:
            if e.response.get("error") == "not_in_channel":
                raise RuntimeError("the bot is not in SLACK_TEST_CHANNEL_ID: type /invite @<bot name> in that channel") from e
            raise
        detail += f"; read {len(hist.get('messages', []))} message(s) from the test channel"
    else:
        detail += "; SLACK_TEST_CHANNEL_ID not set (optional: the channel the live alert test posts in)"
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
                chan = next((c for c in target.text_channels if c.permissions_for(target.me).read_message_history), None)
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


@check("LLM")
def deepseek():
    if not settings.llm_api_key:
        raise RuntimeError("no LLM key set (LLM_API_KEY or DEEPSEEK_API_KEY)")
    from pipeline.llm import _client, _extra, _strip_think

    resp = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        max_tokens=5,
        **_extra(),
    )
    return f"{settings.llm_model} at {settings.llm_base_url} replied '{_strip_think(resp.choices[0].message.content).strip()}'"


if __name__ == "__main__":
    for fn in (falkordb, slack, discord_check, github, deepseek):
        fn()
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
