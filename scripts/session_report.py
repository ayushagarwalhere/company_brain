"""Measures an unscripted Slack session: what people said and what the bot did, for labelling.

    python -m scripts.session_report --since "2026-10-17T15:00" [--until ...] [--json out.json]

Reads #product, #engineering and #support-escalations through the Slack API (the bot must be in them) and prints:
messages per person, every Drift Monitor alert with the message that triggered it, and every command reply.
Each alert gets a line to label by hand: was the triggering message really a decision that changes a ticket?
"""

import argparse
import json
from datetime import UTC, datetime

from connectors.slack import CHANNELS, channel_ids, client, paged


def _ts(iso: str) -> float:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO time, e.g. 2026-10-17T15:00 (UTC unless an offset is given)")
    ap.add_argument("--until", help="ISO time; default now")
    ap.add_argument("--json", help="also write the report here")
    a = ap.parse_args()
    c = client()
    me = c.auth_test()["user_id"]
    ids = channel_ids(c)
    names: dict[str, str] = {}

    def who(uid: str | None) -> str:
        if not uid:
            return "?"
        if uid not in names:
            u = c.users_info(user=uid)["user"]
            names[uid] = u.get("real_name") or u.get("name") or uid
        return names[uid]

    oldest, latest = str(_ts(a.since)), str(_ts(a.until)) if a.until else None
    people: dict[str, int] = {}
    alerts, replies = [], []
    for ch in CHANNELS:
        if ch not in ids:
            continue
        kw = {"channel": ids[ch], "oldest": oldest, "limit": 200, **({"latest": latest} if latest else {})}
        for m in paged(c.conversations_history, "messages", **kw):
            thread = [m]
            if m.get("reply_count"):
                thread = list(paged(c.conversations_replies, "messages", channel=ids[ch], ts=m["ts"], limit=200))
            for x in thread:
                if x.get("subtype") and x.get("subtype") != "bot_message":
                    continue
                text = x.get("text", "")
                if x.get("username"):  # seeded scenario messages: posted by the bot under a persona name; not part of a session
                    continue
                if x.get("user") == me or x.get("bot_id"):
                    item = {"channel": ch, "ts": x["ts"], "thread_root": m.get("text", "")[:200], "root_author": who(m.get("user")), "reply": text[:400]}
                    (alerts if "Requirement drift" in text else replies).append(item)
                else:
                    people[who(x.get("user"))] = people.get(who(x.get("user")), 0) + 1
    total = sum(people.values())
    print(f"{total} human messages from {len(people)} people: " + ", ".join(f"{k} {v}" for k, v in sorted(people.items(), key=lambda kv: -kv[1])))
    print(f"{len(alerts)} drift alerts, {len(replies)} other bot replies\n")
    for n, x in enumerate(alerts, 1):
        print(f"[{n}] #{x['channel']} — {x['root_author']}: {x['thread_root']}")
        print(f"    bot: {x['reply'].splitlines()[0] if x['reply'] else ''}")
        print("    label: correct / false alert ?\n")
    if a.json:
        json.dump(
            {"since": a.since, "until": a.until, "messages": total, "people": people, "alerts": alerts, "replies": replies},
            open(a.json, "w", encoding="utf-8"),
            indent=1,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    main()
