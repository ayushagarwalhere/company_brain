# Context Graph Drift Monitor

> **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB). Track: **Company Brain**.

**Decisions change in chat. Tickets keep the old text, and PRs ship the old version.** This agent keeps a FalkorDB context graph of a team's Slack, Discord, tickets, GitHub PRs and docs. When an owner decides something new in chat and nothing newer replaces it, no PR ships it, and nobody keeps the old scope, it replies **in the thread** with the graph path as evidence, and then gets the fix done.

**▶ Product tour:** the homepage's *Take the product tour* button walks through every feature on a private sandbox company, and each step's button performs the real action (`/?org=tour&tour=1`).

[Full results](docs/RESULTS.md) · [Architecture, setup and tests](docs/DETAILS.md) · [Every query](docs/QUERIES.md) · [How it works](docs/EXPLAIN.md)

![Demo: an open drift, the fix plan read from the graph, a non-owner refused, the owner approving, follow-ups assigned, a multi-hop answer, the graph](docs/demo.gif)

<sub>Frames from the running app, captured with real clicks on a demo copy of the graph; not a screen recording.</sub>

**In a real Slack workspace**, a ticket owner's message got this in-thread alert within seconds:

![Slack thread: the ticket owner's decision and Drift Monitor's in-thread drift alert](docs/real-slack-thread.png)

## What the company brain answers

| Question | How the graph answers it |
|---|---|
| **Did we ship what we decided?** | Drift: a chat requirement nothing `SUPERSEDES`, no PR `IMPLEMENTS`, nobody `DISMISSES` |
| **Who decided it, where, and what did it replace?** | The decision's message, author, channel and the version chain it amends |
| **Who owns this, who knows the most?** | Ticket owners, people ranked by decisions > PRs > tickets > messages, and the bus factor |
| **How are these two connected?** | The shortest causal path (`algo.SPpaths`), e.g. a support agent's message → a thread → a ticket → a PR |
| **What has to happen now, and who does it?** | A fix plan: the ticket, every stale PR and doc, each assigned to its author |
| **What did the sprint decide, ship and leave behind? What has no paper trail?** | Sprint retro; PRs with no ticket, closed tickets with no PR, tickets nobody discussed |
| **If Project Alpha slips two weeks, which teams and client deliverables are hit?** | `Project -INCLUDES-> Ticket -[:BLOCKS*]-> Ticket <-INCLUDES- Project`, then `Deliverable -NEEDS-> Project`, `-FOR-> Client`, and the people doing the work `-MEMBER_OF-> Team` |
| **What is this feature's spec, who introduced each part, and how is the work going?** | A map per feature: every requirement version and who wrote or said it, the tickets, PRs, tasks and docs on it, and what depends on it |

## The agent gets work done

It doesn't stop at the alert. In the alert thread ([`pipeline/work.py`](pipeline/work.py)):

```
zara:  @Drift Monitor fix it
bot:   🔒 Only BD-102's owners can decide this: Maya Chen (created it) or Kenji Watanabe (assigned). zara can't.
maya:  @Drift Monitor plan
bot:   1. Write the decision into BD-102 (done by me when an owner approves)
       2. Change PR #7 "Add export button to ticket list" to the new requirement → kenji
       3. Update DOC-1 "PRD — Ticket export" → maya
       Also tell: sofia, arjun, liam. Who can approve: Maya Chen or Kenji Watanabe.
maya:  @Drift Monitor fix it
bot:   ✅ Done. BD-102 now carries the decision. Follow-ups opened: T-1 → kenji, T-2 → maya
```

- **The plan is a graph read:** who wrote each stale PR and doc, who owns the ticket, who else is involved.
- **Only owners decide.** Approving writes the decision into the ticket and opens follow-up `Task` nodes assigned to the right people. They survive every rebuild.
- **Same actions** in Slack and Discord threads, on the dashboard ("Fix plan", "Approve fix", "Open follow-ups") and in Q&A.
- **Guardrails:** 15 fixed graph tools on read-only `GRAPH.RO_QUERY`; an LLM answer that names an id no tool returned, skips the tools, or withholds results the asker may see is replaced by the grounded one; "I couldn't find BD-999 in the graph" instead of a guess.

The refusal and plan are the agent's actual replies on the live-Slack graph; the flow is tested in [`tests/test_work.py`](tests/test_work.py).

## Staying current, and staying private

**When a doc changes** (Google Doc, Notion page, PRD file), the graph and the vectors move together, in one store ([`pipeline/knowledge.py`](pipeline/knowledge.py)):
- docs are split into `Chunk` nodes whose embeddings live in a **FalkorDB vector index**, one hop from their document, author, tickets and access list. There's no second vector database to keep in step;
- an edit re-embeds **only the chunks whose text changed** (content hash), deletes chunks that disappeared, and recomputes the doc's `MENTIONS` edges: links added *and removed*, so the doc's stale/current status follows the edit;
- **Google Drive** ([`connectors/gdrive.py`](connectors/gdrive.py)) reads Drive's change feed from a saved position, exports each changed Doc and its sharing, and syncs it; Drive's push notification (`POST /api/ingest/gdrive`) triggers a pass. It's tested against a fake Drive API, not yet a real Drive.

**Who can see what** ([`pipeline/access.py`](pipeline/access.py)): a document can be restricted to groups or people (doc metadata `access: leads, hr`, or its Google Drive sharing). Enforcement happens in three places, so one miss doesn't leak:
1. **in the query:** the vector search filters by the viewer's grants inside FalkorDB;
2. **in every agent tool:** rows and evidence paths about a document the viewer can't see are removed *before* the LLM or the rules agent reads them, so the model can't leak what it never received;
3. **on every API response:** the same redaction runs on the JSON body.

```
zara (QA):  What is everyone's salary?
bot:        I don't have information on that you can access.        ← no data, and no hint the doc exists
maya (lead): What is everyone's salary?
bot:        From Compensation bands 2026 (confidential) (DOC-5, by arjun): … Senior Engineer: 120,000 to 155,000 …
```

The viewer is the chat user in Slack and Discord, the `X-User` header on the API (in production, the SSO identity), and anonymous otherwise. Tested in [`tests/test_knowledge.py`](tests/test_knowledge.py).

## Impact analysis

*"If we delay the launch of Project Alpha by two weeks, which other teams and downstream client deliverables will be impacted?"* is answered by walking the graph ([`pipeline/impact.py`](pipeline/impact.py)): from the project to its tickets, through every ticket they block (`[:BLOCKS*1..8]`, one variable-length query), to the projects waiting on them, the client deliverables that need any of those projects, and the teams of the people doing the work.

```
If Project Alpha slips 14 days, its launch moves from 2026-10-23 to 2026-11-06.
Downstream: Project Beta slips 3 days: BD-108 blocks BD-109 (the dashboard's SLA metrics reuse the export pipeline).
- Acme Corp: Custom-range ticket export for Acme's Q4 audit, due 2026-10-30: misses its due date by 7 days (owner liam).
- Globex: Weekly SLA report, due 2026-11-10: tight, 4 days left.
- Umbrella Inc: Bulk ticket export, due 2026-11-13: on track, 7 days left.
Teams affected (4): Backend (Arjun, Sofia) · Customer Success (Liam) · Product & Design (Maya) · Web (Kenji).
Also open: BD-101 has a chat decision the ticket doesn't carry yet. Worth folding into the new plan.
```

The dashboard's **Impact** section draws this as a graph (teams → people → project → tickets → blocked tickets → waiting projects → deliverables → clients) with a delay picker, and the **Graph → Map** view shows every feature the same way: each spec version and who introduced it, the work on it, and what depends on it. The schedule rule is deliberately simple (a project can't launch before the work it waits on; no task durations).

## Why it needs a graph

Drift is a **time-ordered path question**. Every ticket version and chat change is its own `Requirement`, linked by `SUPERSEDES`:

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)   // still the newest version
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)   // nothing shipped it
  AND NOT (:Decision)-[:DISMISSES]->(r)       // nobody kept the old scope
```

- **Context that ids miss:** the deciding messages never name a ticket; threads, people and time connect them. With ticket ids only, both real drifts are missed.
- **Version reasoning:** switch off `SUPERSEDES`/`IMPLEMENTS` and half the alerts become false (precision 1.00 → 0.50). CI fails if that regresses.
- **Evidence with every answer,** and **multi-hop paths** (`algo.SPpaths`, p50 6.1 ms at 22,940 nodes).

| FalkorDB feature | Used for |
|---|---|
| Cypher anti-patterns | The drift query, with its evidence in the same query ([`graph/queries.py`](graph/queries.py)) |
| `algo.SPpaths` | "How is X connected to Y?", answered with the path |
| Variable-length paths `[:REPLY_TO*1..5]`, `[:BLOCKS*1..8]` | The live monitor inherits context from the thread; impact analysis follows dependencies to any depth |
| `GRAPH.RO_QUERY` | Every agent tool is read-only |
| Vector index (`db.idx.vector.queryNodes`) | Document chunks searched by meaning, filtered by access rights in the same query |
| Full-text and range indexes, `GRAPH.EXPLAIN` | Search; CI fails on any label scan |
| `UNWIND … MERGE`, one graph per tenant, paging | Idempotent ingest, isolated orgs, no truncation at scale |

Honest boundary: with the same extracted facts and version chain, a SQL anti-join finds the same drift. The graph's job is the model, the evidence, the traversal and the actions ([Results §2](docs/RESULTS.md#2-graph-vs-a-relational-baseline)).

## Proof it runs

- **Real Slack:** a decision posted in a real workspace got the in-thread alert above; a rebuild from Slack history found it too ([`docs/REAL_RUN.md`](docs/REAL_RUN.md)).
- **Real GitHub:** a merged PR, [brightdesk-demo#1](https://github.com/Dakshhhhh-ops/brightdesk-demo/pull/1), read through the GitHub API, closed the BD-103 drift via `IMPLEMENTS`.
- **Real drift in a real repo:** in [golang/go#77441](https://github.com/golang/go/issues/77441) the accepted API (`HandleRequest(…) error`, amended in a comment) differs from the issue body, which still says `ServeHTTP` with no error. The extractor finds the change (after a fix to its evidence guard, so not held-out). Searching 289 FalkorDB and Excalidraw comments found no drift: their 2 real scope decisions had already reached a PR ([results §7](docs/RESULTS.md#7-looking-for-real-drift-in-real-repos)).
- **Scale:** 100 of 100 planted drifts in a 22,940-node graph, 0 false; drift query p50 39 ms.
- **Tested:** 141 tests, CI with ruff, mypy, the ablation gate and a query-plan check.

## Results at a glance

From [`docs/RESULTS.md`](docs/RESULTS.md). gpt-oss-120b = OpenAI's open-weight model on Groq's free tier; qwen3:8b = a small local model.

| Measurement | Result |
|---|---|
| Synthetic company (300 messages): drift P / R | **1.00 / 1.00** (rules and qwen3:8b) |
| Q&A, gpt-oss-120b agent over the graph / retrieval into the same model | **0.84** / 0.71 |
| Q&A, rules agent (no LLM) / raw top-25 passages | 0.86 / **0.98** (the dump is five times longer) |
| Real GitHub text, rules / gpt-oss-120b | false positives still flagged 25/25 / **2/25**; recall 1/7 / **2/7** |
| 500 noise messages, rules / qwen3:8b | both real drifts found; 14 / **1** false alerts |
| Stress test, 22,940 nodes | **100 / 100** planted drifts |
| Real drift search, FalkorDB + Excalidraw (289 comments) | 81 flags checked against their GitHub threads (AI-written verdicts), **0 confirmed drift** |

## Known weaknesses

- **Extraction on real text is the weak link, and it is tuned for precision on purpose.** On real GitHub text gpt-oss-120b was right every time it flagged something (precision 1.00) but found only 2 of 7 real decisions. For a bot that posts into people's threads that is the right trade-off: a false alert is spam and costs trust, a missed one costs nothing new. And nothing changes without a ticket owner approving it. The real-data labels were made by the AI assistant; 0 of 25 re-checked by me.
- **Written against the test data:** the rules, prompts and thresholds were tuned on the synthetic company, so its 1.00s are an upper bound.
- **Small demo:** two real drifts; "half the alerts are false" is 2 of 4.
- **Document search uses a local, lexical embedding unless you configure one** (`EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_API_KEY`); its thresholds were set on 12 hand-written questions. The Google Drive connector has only run against a fake Drive API.
- **The org layer behind impact analysis is hand-written demo data** ([`data/scenario/org.json`](data/scenario/org.json): teams, projects with launch dates, three ticket dependencies, four clients and their deliverables). In a real company it would come from the tracker's projects and "blocks" links, the HR system and the CRM; no connector for those exists yet.
- **The live runs used the synthetic company's messages** and one PR I wrote, in a one-person workspace.

Full list: [`docs/RESULTS.md`](docs/RESULTS.md#limitations).

## Quick start

```bash
pip install -r requirements.txt && cp .env.example .env
docker run -d -p 6379:6379 falkordb/falkordb:v4.22.1
python -m pipeline.build                       # build the graph, print drift
cd web && npm install && npm run build && cd ..
uvicorn api.main:app --port 8000               # dashboard on http://localhost:8000
```

The LLM is optional (rules otherwise). LLM setup, real Slack/GitHub, Docker/Render and the test list: [`docs/DETAILS.md`](docs/DETAILS.md).

## AI assistant disclosure

Built with help from an AI coding assistant (Claude Code), as the hackathon rules allow. The idea, the scenario and the graph model come from my project plan, and I can explain every part ([`docs/EXPLAIN.md`](docs/EXPLAIN.md)). The real-data labels were made by the assistant and are marked as such.
