# Submission video (about 2½ minutes, real screen recording)

Record with Windows **Win + Alt + R** (Xbox Game Bar) or OBS, 1080p, browser full-screen. Hide bookmarks (Ctrl+Shift+B).

**Before recording**
- Bot and dashboard running; `python -m scripts.demo_reset --api http://localhost:8000` so only BD-101 and BD-103 are open.
- Tabs: (1) Slack `#engineering`, (2) the dashboard, (3) the README on GitHub.
- **Between takes, restart the bot** (`python -m bots.slack_bot`) or wait 5 minutes: it remembers alerts per ticket for 5 minutes, and the dashboard reset doesn't clear that.
- Have this ready to paste in Slack, as plain text (no code formatting): *Decision: the export button must also offer a JSON download, BD-102.*

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:15 | Dashboard hero | scroll slowly | "Teams decide things in Slack. The ticket keeps the old text, and the PR ships the old version. Nobody notices until a customer does. This is a company brain on FalkorDB that catches it." |
| 0:15–0:40 | Slack `#engineering` | paste the message, send, wait for the reply | "I own BD-102. I post a decision in Slack… and within seconds the bot answers in the thread: BD-102 still says the old thing, PR #7 shipped the old version, and here's the graph path that proves it." |
| 0:40–1:00 | Dashboard → Open drift | show the new BD-102 card, open **Graph path** | "The same drift is on the dashboard: what the ticket says, what was decided, who decided it and where, and the PRs and docs still on the old version." |
| 1:00–1:20 | Feature graph | pick the drift, hover the lit path | "This is the graph behind it: person, message, requirement, ticket, PR. The decision never named a ticket; the thread and the people connect it." |
| 1:20–1:45 | Ask the graph | ask *Who knows the most about ticket export?*, then *How is liam connected to PR #6?*, then *Is BD-999 stale?* | "It's not only drift. Who knows the most, and how two things are connected: a support agent's message, a thread, a ticket, a PR, four hops that no join on ticket ids finds. Every answer shows its path. And when something isn't in the graph, it says so instead of guessing." |
| 1:45–2:10 | Slack, **in the alert thread** | as yourself (maya): `@Drift Monitor plan`, then `@Drift Monitor fix it` | "It doesn't stop at the alert. The plan comes from the graph: the ticket, PR #7 to kenji who wrote it, the PRD to its author, who else to tell. Only the ticket's owners can approve. I own it, so: fix it. It writes the decision into BD-102 and assigns the follow-ups." |
| 2:10–2:20 | Dashboard → Open drift | show **Open follow-ups**; on another card open **Fix plan** and press **Approve fix as zara** | "Same actions on the dashboard. Zara doesn't own this ticket, so the agent refuses and says who can decide." |
| 2:00–2:20 | Coverage & risk, then Sprint retro | scroll | "The same graph shows knowledge held by one person, PRs with no ticket, and what a sprint decided, shipped and left behind." |
| 2:20–2:35 | README on GitHub | scroll Results at a glance → Known weaknesses | "Everything is measured: an ablation in CI, 100 of 100 drifts at 23 thousand nodes, a SQL baseline. And I list where it's weak: extraction on real-world text is the open problem." |

**After recording:** run the reset again. Upload the video (YouTube unlisted or Loom), and put the link at the top of the README.

---

# 90-second demo

**Before recording:**
- Run `python -m scripts.demo_reset --api http://localhost:8000`. It must print `"ok": true` with drift on BD-101 and BD-103.
- Open `http://localhost:8000/?static` for a projector, or without `?static` for the animated version.
- Keep a second tab on Slack or Discord only if the bots are running. Everything below also works from the dashboard alone.

Checked with the LLM **off** (rules extractor and rules agent), the only mode I could run. With a working DeepSeek key the same steps use the LLM. The wording of answers changes; the drift outcomes shouldn't.

| Time | Screen | Say |
|---|---|---|
| 0–10 s | Hero | "Decisions happen in chat, requirements live in tickets, code ships in PRs. Nothing links them, so the ticket goes stale and the team ships the old version. This is a FalkorDB context graph that catches that." |
| 10–30 s | **Open drift**: the BD-101 card | "In Slack on 22 September, Maya changed the CSV export to 12 months plus custom fields. BD-101 still says 30 days, PR #6 shipped 30 days, and the PRD is stale. This is the graph path behind the alert: message, requirement, ticket, PR. It's one Cypher query: a chat requirement that nothing supersedes and no PR implements." |
| 30–50 s | **Simulate the team** → Chat message. Author `maya`, keep the default text ("…JSON download, BD-102"), then **Send** | "Maya owns BD-102, so this counts as a decision. The monitor links it to the feature, sees the ticket doesn't say it, and raises a drift with the path." *(Optional, 5 s: switch the author to `zara` and post again → `no-decision-rights`. "Only a ticket's owner can change it from chat. That cut false changes by 71% in my noise test.")* |
| 50–65 s | **Simulate** → Ticket edit. BD-101, paste "Admins can export tickets for any custom date range up to 12 months as CSV, including all custom fields as extra columns.", then save | "When the ticket catches up, the new version SUPERSEDES the chat requirement and the drift resolves. A typo-fix edit wouldn't." |
| 65–78 s | **Ask the graph**, type "What does BD-103 say and is it still accurate?" | "Answers come from graph tools and cite the path. Without an LLM it's a rules agent, and it says so." |
| 78–90 s | README → **Known weaknesses** | "I measured where it fails. On real GitHub issues the rule extractor's drift flags were all false. Under 500 noise messages, the latest misread message used to bury the real decision. I found that bug in the supersession chain, fixed it, and both drifts came back, at the cost of more false alerts. The graph logic holds at 60× scale. Extraction is the open problem, and the README has the local-LLM numbers next to the rules." |

**After recording:** run `python -m scripts.demo_reset --api http://localhost:8000` again. It undoes the simulated message and the ticket edit, and clears the alert cooldown.

**If something goes wrong:**
- **Simulate shows `cooldown` or `already-alerted`:** you posted the same thing within 5 minutes. Reset with `--api`.
- **Simulate shows `no-decision-rights` for maya:** the text names a ticket maya doesn't own. Use BD-101, BD-102, BD-103 or BD-104.
- **The dashboard doesn't refresh after a reset:** reload. SSE is off in `?static`.
