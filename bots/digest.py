"""Drift digest: one message summarising open drift and coverage risks, for a daily schedule.

    python -m bots.digest --dry-run                 # print it
    python -m bots.digest --slack C0123456789       # post to a Slack channel (bot must be in it)
    python -m bots.digest --discord 123456789012    # post to a Discord channel (REST, no gateway needed)

Every line links back to its source, and each drift carries its graph path.
"""

import argparse

import requests

from agent.tools import drift_path
from config import settings
from graph import queries as Q
from graph.db import get_graph


def build(g=None) -> str:
    g = g or get_graph()
    drift = Q.drift(g)
    risk = [r for r in Q.rows(g, Q.KNOWLEDGE_RISK) if r["top_share"] >= 0.5]
    orphans = Q.rows(g, Q.ORPHAN_PRS)
    done_no_pr = Q.rows(g, Q.DONE_WITHOUT_PR)
    lines = [f"*Drift digest* · {len(drift)} open drift" + ("" if drift else " ✅")]
    for d in drift:
        stale = Q.pr_list(d)
        lines += [
            f"• *{d['feature_name']}* / {d['ticket']}: {d['changed_by']} decided “{d['requirement_text']}” "
            f"on {d['changed_at'][:10]} ({d['source']} #{d['channel']}). Ticket still says “{d['ticket_text']}”. "
            f"Shipped old version: {stale}." + (f" Stale docs: {', '.join(x['title'] for x in d['stale_docs'])}." if d["stale_docs"] else ""),
            f"   `{drift_path(d)}`",
        ]
    if risk or orphans or done_no_pr:
        lines.append("*Coverage*")
    for r in risk:
        lines.append(f"• {r['name']}: {r['top_person']} holds {round(r['top_share'] * 100)}% of the knowledge " f"({r['people']} people involved)")
    for o in orphans:
        lines.append(f"• PR #{o['pr']} “{o['title']}” has no ticket")
    for t in done_no_pr:
        lines.append(f"• {t['ticket']} “{t['title']}” is Done with no linked PR")
    return "\n".join(lines)


def post_slack(channel: str, text: str) -> None:
    from slack_sdk import WebClient

    WebClient(token=settings.slack_bot_token).chat_postMessage(channel=channel, text=text)


def post_discord(channel: str, text: str) -> None:
    text = text.replace("*", "**")
    for i in range(0, len(text), 1900):
        r = requests.post(
            f"https://discord.com/api/v10/channels/{channel}/messages",
            timeout=15,
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            json={"content": text[i : i + 1900]},
        )
        r.raise_for_status()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slack", metavar="CHANNEL_ID")
    ap.add_argument("--discord", metavar="CHANNEL_ID")
    a = ap.parse_args()
    msg = build()
    if a.dry_run or not (a.slack or a.discord):
        print(msg)
    if a.slack:
        post_slack(a.slack, msg)
    if a.discord:
        post_discord(a.discord, msg)
