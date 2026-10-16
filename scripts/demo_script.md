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
| 30–50 s | **Simulate the team** → Chat message. Author `maya`, keep the default text ("…JSON download, BD-102"), then **Post message** | "Maya owns BD-102, so this counts as a decision. The monitor links it to the feature, sees the ticket doesn't say it, and raises a drift with the path." *(Optional, 5 s: switch the author to `zara` and post again → `no-decision-rights`. "Only a ticket's owner can change it from chat. That cut false changes by 71% in my noise test.")* |
| 50–65 s | **Simulate** → Ticket edit. BD-101, paste "Admins can export tickets for any custom date range up to 12 months as CSV, including all custom fields as extra columns.", then save | "When the ticket catches up, the new version SUPERSEDES the chat requirement and the drift resolves. A typo-fix edit wouldn't." |
| 65–78 s | **Ask the graph**, type "What does BD-103 say and is it still accurate?" | "Answers come from graph tools and cite the path. Without an LLM it's a rules agent, and it says so." |
| 78–90 s | README → **Known weaknesses** | "I measured where it fails. On real GitHub issues the rules extractor's drift flags were all false, and noise can hide real drift. The graph logic holds at 60× scale. Extraction is the open problem, and the LLM path is built for it but I couldn't measure it." |

**After recording:** run `python -m scripts.demo_reset --api http://localhost:8000` again. It undoes the simulated message and the ticket edit, and clears the alert cooldown.

**If something goes wrong:**
- **Simulate shows `cooldown` or `already-alerted`:** you posted the same thing within 5 minutes. Reset with `--api`.
- **Simulate shows `no-decision-rights` for maya:** the text names a ticket maya doesn't own. Use BD-101, BD-102, BD-103 or BD-104.
- **The dashboard doesn't refresh after a reset:** reload. SSE is off in `?static`.
