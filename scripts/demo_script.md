# Submission video (about 3 minutes, real screen recording)

Record with Windows **Win + Alt + R** (Xbox Game Bar) or OBS, 1080p, browser full-screen. Hide bookmarks (Ctrl+Shift+B).

**Rules for what's on screen** (a judge who spots a fake trusts nothing after it):
- Slack scenes are the **real** Slack workspace with the real bot. Don't show the dashboard's *Simulate* panel as if it were Slack; if you use it, say "simulated message".
- The demo company's docs, tickets and HR records are sample data, and their source badges say "(demo)". Say "sample doc", never "our Notion": there is no Notion connector.
- Numbers come from the README's proof table, nothing else.

**Before recording**
- Bot and dashboard running; `python -m scripts.demo_reset --api http://localhost:8000` so only BD-101 and BD-103 are open.
- Tabs: (1) Slack `#engineering`, (2) the dashboard, (3) a terminal in `examples/mcp-demo` with two Claude Code windows ready (see its README), (4) the overview's *Your repo* section with FalkorDB/FalkorDB built, (5) the README on GitHub.
- **Between takes, restart the bot** (`python -m bots.slack_bot`) or wait 5 minutes: it remembers alerts per ticket for 5 minutes, and the dashboard reset doesn't clear that.
- Have this ready to paste in Slack, as plain text (no code formatting): *Decision: the export button must also offer a JSON download, BD-102.*
- For the MCP clip: `git checkout helpdesk/export.py` in `examples/mcp-demo` before each take.

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:12 | Overview hero | scroll slowly | "Teams decide things in Slack. The ticket keeps the old text, and the PR ships the old version. This is a company brain on FalkorDB that catches it." |
| 0:12–0:35 | Slack `#engineering` | paste the message, send, wait for the reply | "I own BD-102. I post a decision in Slack… and within seconds the bot answers in the thread: BD-102 still says the old thing, PR #7 shipped the old version, and here's the graph path that proves it." |
| 0:35–0:52 | Dashboard → Open drift | show the new BD-102 card, open **Graph path** | "The same drift is on the dashboard: what the ticket says, what was decided, who decided it and where, and the PRs and docs still on the old version." |
| 0:52–1:22 | Terminal, `examples/mcp-demo` | left: `claude --strict-mcp-config` → *implement BD-101*; right: `claude` → *implement BD-101*; show both `export.py` files | "Now the same problem for a coding agent. Without company context, Claude Code builds what the ticket says: thirty days. With our MCP server it first asks for the current spec, and builds what Maya decided in Slack: twelve months and every custom field, and it tells me PR #6 shipped the old version." |
| 1:22–1:45 | Ask the graph | ask *Why is the database migration delayed and who can approve an override?*, point at the sources | "It answers across systems: a Slack message, a design doc, the ticket, the assignee's time off and their manager. Every answer shows its path and where each piece came from; here the doc, ticket and HR record are the demo company's sample data, and the badges say so." |
| 1:45–2:10 | Overview → Your repo | open FalkorDB/FalkorDB, scroll the result | "It's not only our sample company. Paste any public GitHub repo: who knows what, which PRs close which issues, open issues nobody is working on. Drift on real text is our weakest part, and the page says so next to every flag." |
| 2:10–2:30 | Slack, **in the alert thread** | as yourself (maya): `@Drift Monitor plan`, then `@Drift Monitor fix it` | "It doesn't stop at the alert. The plan comes from the graph. Only the ticket's owners can approve. I own it, so: fix it. It writes the decision into BD-102 and assigns the follow-ups." |
| 2:30–2:50 | README on GitHub | the proof table, then **Honest limits** | "Everything is measured: drift precision falls from one to a half without the version edges, a hundred of a hundred drifts at twenty-three thousand nodes, and a real drift in golang/go. And the README lists where it's weak." |

**After recording:** run the reset again. Upload the video (YouTube unlisted or Loom), and put the link at the top of the README (replace `https://VIDEO_URL`).

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
| 30–50 s | **Simulate the team** → Chat message. Author `maya`, keep the default text ("…JSON download, BD-102"), then **Send** | "This is a simulated message, the same pipeline the Slack bot runs. Maya owns BD-102, so this counts as a decision. The monitor links it to the feature, sees the ticket doesn't say it, and raises a drift with the path." *(Optional, 5 s: switch the author to `zara` and post again → `no-decision-rights`. "Only a ticket's owner can change it from chat. That cut false changes by 71% in my noise test.")* |
| 50–65 s | **Simulate** → Ticket edit. BD-101, paste "Admins can export tickets for any custom date range up to 12 months as CSV, including all custom fields as extra columns.", then save | "When the ticket catches up, the new version SUPERSEDES the chat requirement and the drift resolves. A typo-fix edit wouldn't." |
| 65–78 s | **Ask the graph**, type "What does BD-103 say and is it still accurate?" | "Answers come from graph tools and cite the path. Without an LLM it's a rules agent, and it says so." |
| 78–90 s | README → **Honest limits** | "I measured where it fails. On real GitHub issues the rule extractor's drift flags were all false. Under 500 noise messages, the latest misread message used to bury the real decision. I found that bug in the supersession chain, fixed it, and both drifts came back, at the cost of more false alerts. The graph logic holds at 60× scale. Extraction is the open problem, and the README has the local-LLM numbers next to the rules." |

**After recording:** run `python -m scripts.demo_reset --api http://localhost:8000` again. It undoes the simulated message and the ticket edit, and clears the alert cooldown.

**If something goes wrong:**
- **Simulate shows `cooldown` or `already-alerted`:** you posted the same thing within 5 minutes. Reset with `--api`.
- **Simulate shows `no-decision-rights` for maya:** the text names a ticket maya doesn't own. Use BD-101, BD-102, BD-103 or BD-104.
- **The dashboard doesn't refresh after a reset:** reload. SSE is off in `?static`.
