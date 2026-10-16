"""Builds data/scenario/messages.json = handwritten signal messages + seeded noise.

Noise never mentions the three tracked features (export, SLA, dark mode), so the
answer key stays exact. It does mention the other tickets, which gives
entity resolution realistic distractors.

    python -m scripts.generate_messages
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = ROOT / "data" / "scenario"
TARGET_TOTAL = 300
SEED = 15

PEOPLE = ["maya", "arjun", "sofia", "dev", "kenji", "priya", "liam", "zara"]
CHANNELS = {
    ("slack", "engineering"): ["arjun", "sofia", "kenji", "dev", "zara"],
    ("slack", "product"): ["maya", "liam", "priya", "arjun"],
    ("slack", "support-escalations"): ["liam", "maya", "arjun", "zara"],
    ("discord", "engineering"): ["dev", "zara", "arjun", "sofia"],
    ("discord", "design"): ["priya", "kenji", "maya"],
    ("discord", "random"): PEOPLE,
}

SMALL_TALK = [
    "morning all ☀️",
    "anyone up for lunch at 1?",
    "coffee machine on 3rd floor is fixed finally",
    "happy friday!",
    "who's in the office tomorrow?",
    "brb, meeting",
    "lol",
    "thanks!",
    "nice 🎉",
    "is the wifi slow for anyone else?",
    "I'll be out Monday, dentist",
    "good weekend everyone",
    "did anyone see the match last night?",
    "new snacks in the kitchen",
    "running 5 min late to standup",
    "that demo went well 🙌",
    "ty",
    "+1",
    "on it",
    "sounds good",
]
STANDUP = [
    "Standup: yesterday reviews, today {t}, no blockers.",
    "Yesterday: {t}. Today: same, plus code review. Blockers: none.",
    "Working on {t} today. Might need a second pair of eyes this afternoon.",
    "Finished {t}, picking up the next thing from the board.",
]
TOPICS = {
    "engineering": [
        "the login rate limit work (BD-107)",
        "search pagination bug BD-112",
        "dependency bumps (BD-111)",
        "CI caching",
        "the e2e timeouts on main",
        "API docs for BD-114",
        "the staging DB migration",
        "reviewing PRs",
        "a memory leak in the worker",
        "log noise in prod",
    ],
    "product": [
        "customer interviews",
        "pricing page copy",
        "Q4 roadmap draft",
        "the onboarding funnel numbers",
        "churn report",
        "the reporting dashboard idea",
        "release notes",
    ],
    "support-escalations": [
        "a password reset loop for Initech",
        "Globex billing question",
        "an Acme user locked out",
        "an Umbrella Inc. attachment upload failure",
        "a customer asking about SSO",
    ],
    "design": [
        "avatar upload mocks (BD-113)",
        "new empty-state illustrations",
        "the onboarding typo BD-110",
        "icon set cleanup",
        "spacing on the settings page",
    ],
    "random": ["weekend plans", "a podcast recommendation", "the team offsite", "a good keyboard"],
}
CHATTER = {
    "engineering": [
        "Heads up: staging is down for ~10 min while I run migrations.",
        "Can someone review my PR? Small one.",
        "CI is green again.",
        "Found the cause of the memory leak: unbounded cache in the worker.",
        "BD-112 is reproducible: two tickets with the same created_at.",
        "Rate limit for logins (BD-107): 10 attempts / 5 min, then 15 min lock. Sound right?",
        "Merged the dependency bumps for BD-111, watch for deprecation warnings.",
        "Prod deploy done ✅",
        "Who owns the cron config these days?",
        "Reminder: please squash-merge.",
        "Rolling back the last deploy, seeing 500s on /login.",
        "Fixed, it was a missing env var.",
    ],
    "product": [
        "Roadmap draft for Q4 is in the doc, comments welcome.",
        "Onboarding completion went from 61% to 68% after the copy change.",
        "Three customers asked about SSO this week.",
        "Release notes for this sprint are drafted.",
        "Pricing page experiment starts Monday.",
    ],
    "support-escalations": [
        "Initech user stuck in a password reset loop, can someone look?",
        "Globex wants an invoice resent, handled.",
        "Umbrella can't upload attachments over 10 MB, is that expected?",
        "Acme user locked out after too many logins, which is good I guess 😅",
        "Customer asking if we support SAML SSO. Not yet, right?",
    ],
    "design": [
        "Avatar upload mocks for BD-113 are in Figma.",
        "Tweaked the empty states, much friendlier now.",
        "Typo on onboarding (BD-110) is fixed in the copy doc.",
        "Icon set cleanup is about 70% done.",
        "Settings page spacing feels cramped on mobile.",
    ],
    "random": [
        "Anyone tried the new ramen place?",
        "Recommendation: 'Shape Up' is a good read.",
        "Offsite poll closes Friday!",
        "My cat walked across the keyboard and pushed to a branch 🐈",
    ],
}


def working_slots(start: datetime, end: datetime):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main():
    rng = random.Random(SEED)
    signal = json.loads((SCENARIO / "signal_messages.json").read_text(encoding="utf-8"))
    for m in signal:
        m["kind"] = "signal"

    days = list(working_slots(datetime(2026, 9, 14, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC)))
    noise = []
    n_noise = TARGET_TOTAL - len(signal)
    for i in range(n_noise):
        platform, channel = rng.choice(list(CHANNELS))
        author = rng.choice(CHANNELS[(platform, channel)])
        day = rng.choice(days)
        ts = day + timedelta(hours=3, minutes=30) + timedelta(minutes=rng.randint(0, 9 * 60))
        r = rng.random()
        if r < 0.35:
            text = rng.choice(SMALL_TALK)
        elif r < 0.6 and channel != "random":
            text = rng.choice(STANDUP).format(t=rng.choice(TOPICS[channel]))
        else:
            text = rng.choice(CHATTER[channel])
        noise.append(
            {
                "id": f"m_noise_{i + 1:03d}",
                "platform": platform,
                "channel": channel,
                "author": author,
                "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": text,
                "kind": "noise",
            }
        )

    msgs = sorted(signal + noise, key=lambda m: (m["ts"], m["id"]))
    (SCENARIO / "messages.json").write_text(json.dumps(msgs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    by_platform = {p: sum(m["platform"] == p for m in msgs) for p in ("slack", "discord")}
    print(f"{len(msgs)} messages ({len(signal)} signal, {len(noise)} noise) {by_platform}")


if __name__ == "__main__":
    main()
