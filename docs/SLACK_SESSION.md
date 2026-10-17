# Unscripted Slack session: brief and how it is measured

Goal: answer "a one-person workspace replaying synthetic messages" with **real people talking without a script** while
the bot runs live. 2–4 people, about 20 minutes, in the real workspace's `#product`, `#engineering` and
`#support-escalations`.

## Before (organiser, 5 minutes)

1. Invite each person to the workspace and to the three channels.
2. Give each person a teammate from the synthetic company. The bot only treats a message as a decision when its author
   owns the ticket (created it or is assigned), so each person needs an identity that owns something. Put their Slack
   username in that teammate's `"slack"` field in `data/scenario/people.json` (locally; don't commit it), then
   rebuild (`python -m pipeline.build --live --extractor heuristic`) and start the bot (`python -m bots.slack_bot`).
3. Note the start time.

| Teammate | Role | Owns (created or assigned) |
|---|---|---|
| maya | Product manager | BD-101 to BD-104, BD-109 (created) |
| kenji | Frontend | BD-102, BD-104, BD-105, BD-106, BD-110, BD-113 (assigned) |
| sofia | Backend | BD-101, BD-108, BD-111, BD-112 (assigned) |
| dev | Backend, platform | BD-103, BD-107, BD-114, BD-115 (assigned) |
| zara | QA | BD-110, BD-112, BD-115 (created) — a good "no rights on most tickets" voice |

Ticket titles: BD-101 CSV export, BD-102 export button, BD-103 SLA breach notifications, BD-104 SLA settings page,
BD-105 dark mode, BD-107 login rate limit, BD-108 export performance, BD-109 SLA metrics on dashboard,
BD-112 search pagination duplicates, BD-113 avatar upload.

## What to tell the participants

> You work at Brightdesk, a helpdesk SaaS. Talk about the work the way you normally would at work for 20 minutes:
> status, questions, disagreements, ideas, and decisions when you actually reach them. Mention tickets when it's
> natural. Don't try to trigger or avoid the bot, and don't read how it works. If it replies, react like you would to
> any teammate (you can ask it `@Drift Monitor plan`, but you don't have to).

Do not show them the rules, the README or the bot's phrasing.

## After (organiser, 10 minutes)

```bash
python -m scripts.session_report --since 2026-10-17T15:00 --json benchmark/results/slack_session.json
```

It prints the number of human messages per person and every alert with the message that triggered it. Label each
alert by hand, before discussing it with anyone:
- **correct**: the message really was a decision by the ticket's owner that the ticket doesn't reflect;
- **false alert**: anything else.

Also skim for **missed decisions**: an owner clearly decided a change and the bot said nothing.

Report it in one line, whatever it shows: "N people, M unscripted messages, A alerts, C correct, K missed decisions
we noticed." A session with zero alerts is still a result.
