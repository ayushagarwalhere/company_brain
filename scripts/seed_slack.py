"""Posts the scenario's Slack messages into your workspace, in order, and records the seed map.

    python -m scripts.seed_slack

Needs bot scopes chat:write and chat:write.customize (to show each fictional author's
name), and the bot invited to #product, #engineering and #support-escalations.
Re-running skips messages already posted.
"""

import json
import time

from slack_sdk.errors import SlackApiError

from connectors import scenario, seed_map
from connectors.slack import channel_ids, client


def main():
    c = client()
    ids = channel_ids(c)
    people = {p["id"]: p for p in scenario.people()}
    msgs = [m for m in json.loads((scenario.SCENARIO / "messages.json").read_text(encoding="utf-8")) if m["platform"] == "slack"]
    smap = seed_map.load("slack")
    done = {v["id"]: k for k, v in smap.items()}
    missing = {m["channel"] for m in msgs} - set(ids)
    if missing:
        raise SystemExit(f"Create these channels and invite the bot first: {sorted(missing)}")

    for i, m in enumerate(msgs):
        if m["id"] in done:
            continue
        cid = ids[m["channel"]]
        thread_ts = None
        if m.get("thread_of"):
            parent_key = done.get(m["thread_of"])
            thread_ts = parent_key.split(":", 1)[1] if parent_key else None
        while True:
            try:
                r = c.chat_postMessage(
                    channel=cid, text=m["text"], thread_ts=thread_ts, username=people[m["author"]]["name"], icon_emoji=":bust_in_silhouette:"
                )
                break
            except SlackApiError as e:
                if e.response.status_code == 429:
                    time.sleep(int(e.response.headers.get("Retry-After", 2)))
                    continue
                raise
        key = f"{cid}:{r['ts']}"
        smap[key] = {"id": m["id"], "author": m["author"], "ts": m["ts"], "thread_of": m.get("thread_of")}
        done[m["id"]] = key
        if i % 10 == 0:
            seed_map.save("slack", smap)
            print(f"{len(done)}/{len(msgs)}")
        time.sleep(1.1)  # chat.postMessage is ~1 msg/sec per channel
    seed_map.save("slack", smap)
    print(f"done: {len(done)} slack messages")


if __name__ == "__main__":
    main()
