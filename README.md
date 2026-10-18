# Drift Monitor · Company Brain

**Teams change the plan in Slack, the ticket keeps the old one, and people (now coding agents too) build the old one.**
Drift Monitor is a FalkorDB context graph of a company's chat, tickets, pull requests and docs that catches that gap and
hands the current decision to whoever is about to build: a person, or an AI agent over MCP.

![The site: the overview, open drift with its graph path, a cross-tool answer with its sources, a real repo's graph, and the MCP server](docs/demo.gif)

**▶ [Live demo](https://13-63-197-94.sslip.io/demo)**: straight into the guided tour of the demo company. No sign-up, no setup.

**▶ [Video](https://VIDEO_URL)** · **[Try it on your own GitHub repo](https://13-63-197-94.sslip.io/try/FalkorDB/FalkorDB)** · **[Give Claude Code the current spec (MCP)](examples/mcp-demo)**

| Proof | What it shows |
|---|---|
| **1.00 → 0.50** | Drift precision with the graph's version reasoning, and without it (`SUPERSEDES` / `IMPLEMENTS` switched off): half the alerts become false. Synthetic benchmark; CI fails if the full graph drops below 1.00 or if switching version reasoning off stops making drift worse. [Ablation](docs/RESULTS.md#ablation-switch-the-graph-off-piece-by-piece) |
| **100 of 100** | Planted drifts found in a synthetic **22,940-node** graph with no false alarms; the whole-graph drift query runs in 39 ms (p50). [Stress test](docs/RESULTS.md#6-stress-test) |
| **golang/go#77441** | A real drift in the wild: the API the Go team accepted (`HandleRequest(…) error`) is in a comment, while the issue body still proposes `ServeHTTP`. Found while labelling real decisions; the extractor catches it only after a fix made after seeing it, so it isn't a held-out result. [Details](docs/RESULTS.md#7-looking-for-real-drift-in-real-repos) |

## The problem

A product decision usually happens in a conversation. The ticket keeps yesterday's requirement, the PR implements the old scope, and the PRD is stale. Keyword search can find each item, but cannot reliably determine version order, implementation coverage, or who can resolve the mismatch.

Drift Monitor builds the missing context. A message can change a requirement; a requirement amends a ticket; a pull request implements a particular requirement version; a document mentions the ticket; and every edge retains enough provenance to explain the result. The dashboard exposes the evidence path instead of returning an unsupported summary.

## What it does

- **Detects requirement drift.** A chat change is open drift when it is still the newest requirement, no PR implements it, and nobody explicitly kept the old scope.
- **Shows the evidence.** Each alert includes the author, source channel, previous requirement, affected ticket, stale PRs, and stale documents.
- **Answers graph questions.** Ask who decided something, what replaced it, who knows the most, how two entities are connected, or which work and client deliverables depend on a delayed project.
- **Answers across systems.** *"Why is the database migration delayed, and who can approve an override?"* follows a Slack message to a design doc, the doc to its ticket (BD-116), the ticket to its assignee, and the HR record to their manager, with a source badge per system. In the demo the doc, the tickets and the HR records are sample data, and their badges say "(demo)": there is no Notion or HR connector. Project status also changes live: a lead's *"We are cancelling Project Gamma"* updates the graph, with that message as evidence.
- **Creates an auditable fix.** Ticket owners can write the decision into the ticket or keep the old scope. Approval creates follow-up tasks assigned to the people who own the stale PRs and docs.
- **Keeps knowledge current.** Documents are chunked, embedded, access-filtered, and linked to the surrounding graph. Changed chunks are re-embedded by content hash, while removed ticket mentions are removed too.
- **Supports live operations.** Slack and Discord bots monitor threads, the API accepts ticket, document, GitHub, and Google Drive updates, and open dashboards receive Server-Sent Events.

![Open drift with evidence and actions](docs/screenshot-drift.png)

## How the graph works

Connectors normalize Slack, Discord, GitHub, tickets, documents, and the built-in scenario into one event format. The pipeline ingests those events with idempotent `MERGE` writes, extracts requirement changes, resolves features and references, and builds version relationships. Each ticket version is represented as its own `Requirement` node.

The core drift query is deliberately small and explainable:

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)
  AND NOT (:Decision)-[:DISMISSES]->(r)
```

`SUPERSEDES` is not inferred from “latest message wins.” A ticket edit supersedes a chat change only when the new text reflects the decision; cosmetic edits do not hide drift. Chat-to-chat replacement also requires a confident judgment. This version chain is what prevents noise and stale status updates from masking the real issue.

The graph also powers connection answers, feature timelines, retrospectives, expert and bus-factor views, coverage risks, impact analysis, and spec generation. FalkorDB vector search handles document chunks, with viewer permissions applied in the query, before agent tools receive results, and at the API boundary.

![Graph walkthrough: a decision becomes drift](docs/screenshot-chain.png)

## For coding agents: an MCP server

The same graph, as six read-only MCP tools any coding agent can call: `current_spec(ticket)`, `drift`, `who_knows`,
`decision_history`, `impact` and `find` ([`agent/mcp_server.py`](agent/mcp_server.py)). The API serves it at `/mcp`;
locally it also runs over stdio.

```bash
claude mcp add --transport http company-brain https://13-63-197-94.sslip.io/mcp
```

Asked to "implement BD-101", Claude Code without it built what the ticket says: the last 30 days, five columns. With it,
it first called `current_spec("BD-101")`, built the version Maya decided in Slack (any range up to 12 months, every custom
field as a column), cited the decision and said PR #6 had shipped the old version. Both runs, with the code they wrote:
[`examples/mcp-demo/RUNS.md`](examples/mcp-demo/RUNS.md). Two runs are an example, not a measurement.

## Try it on your own repo

The live site takes any public GitHub repo (`/try/owner/name`). It reads the 150 most recently updated issues, 100 PRs and
up to 400 comments, runs the same pipeline with the rules extractor (no LLM; under 20 seconds for FalkorDB/FalkorDB, most of it GitHub's API) into a graph of its own,
and shows who knows what (per label), which PRs close which issues, open issues no PR touches, decisions in comments and
drift. FalkorDB/FalkorDB is built at startup, so it opens at once. Private repos are refused even if the server's token
could read them, and a repo's graph is read-only.

On real text, drift is the weakest part, and the page says so: on 60 hand-labelled real comments the rules extractor's
precision was 0.17 and its recall 0.14, so decisions and drift there are candidates to read. A flag that was already
hand-checked shows that verdict next to it (both FalkorDB flags are known false positives). People, areas and
issue-PR chains come from GitHub's own links. Code: [`pipeline/tryrepo.py`](pipeline/tryrepo.py).

## Agents, guardrails, and actions

The project includes a deterministic rules agent and an optional LLM agent. Its fixed graph tools are read-only (`GRAPH.RO_QUERY`). Answers are grounded in returned rows and evidence paths: if a response names an unknown identifier, skips a required lookup, or includes data outside the viewer's access, it is replaced with a safe response.

LLM extraction accepts any OpenAI-compatible endpoint, including local Ollama. The `auto` mode uses an LLM when available and falls back to heuristics when it is not. Structured extraction requires an evidence quote to appear literally in the source message. Cached extraction results make the benchmark runs reproducible without a GPU or API key.

Human actions are separate from extractor output and survive rebuilds. Only ticket owners or assignees can approve a fix. A decision can be written to the ticket as a new version, or dismissed as an intentional choice to keep the old scope. Slack, Discord, dashboard buttons, and Q&A use the same action path.

## Dashboard and integrations

The React and TypeScript dashboard provides:

- Open drift cards with graph paths, stale PRs/docs, timelines, and approve/dismiss actions.
- Graph exploration, search, feature maps, person profiles, and evidence panels.
- Ask, Retro, Simulate, and Risk views for cross-source questions and coverage gaps.
- Impact analysis for project delays, blocked tickets, teams, and client deliverables.
- A live stream of everything reaching the graph, and a company map of people, teams, projects, clients, deliverables, docs and tickets.
- Live refresh through SSE, per-organisation graphs, scoped caches, rate limiting, metrics, and OpenAPI docs.

The Slack bot uses Socket Mode and posts alerts in the originating thread. Discord is supported through a gateway bot. GitHub pull-request webhooks, ticket-style webhooks, document webhooks, and Google Drive change notifications can all trigger incremental updates. Tokens stay server-side; installation records are kept in the ignored `data/installs.json` file. Every workspace or server that connects through those buttons gets its own private graph, so it never mixes with the demo company or another team.

**For your own team.** The bot's welcome links to your team's dashboard, which opens on *Your setup*: people come from your Slack directory (names, job titles as roles, emails, admins and user groups), Discord roles and GitHub, linked into one person per human by email, name or handle; tickets come from **Jira** (with every description version from its changelog), **Linear** or GitHub issues, PRs from GitHub, and comments count like chat messages. A pass every few minutes keeps it current: new people and titles, ticket edits, new PRs, edited and deleted messages; then features, requirement versions and drift are re-derived. Details and what isn't covered yet (other trackers, a team's own docs, sign-in): [`docs/DETAILS.md`](docs/DETAILS.md#using-it-for-your-own-team).

![A real Slack thread receiving a drift alert](docs/real-slack-thread.png)

## Quick start

Requirements: Python 3.11+, Docker or FalkorDB Cloud, and Node 18+ for the dashboard.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
docker run -d --name falkordb-brain -p 6379:6379 -p 3001:3000 falkordb/falkordb:v4.22.1

python -m scripts.check_setup
python -m pipeline.build
cd web
npm install
npm run build
cd ..
uvicorn api.main:app --port 8000
```

Open `http://localhost:8000`. The default Brightdesk scenario is an eight-person synthetic company with 300 messages, 15 tickets, 12 pull requests, four documents, two planted drifts, and a clean dark-mode control. Use `python -m scripts.demo_reset` to restore the demo state.

The LLM is optional. Without it, deterministic extraction and Q&A still work. For local extraction, configure:

```bash
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:8b
LLM_API_KEY=ollama
LLM_REASONING_EFFORT=none
```

## Real Slack or Discord data

Add the relevant bot credentials to `.env` and follow [`docs/REAL_RUN.md`](docs/REAL_RUN.md). The web overview also provides consent-based “Add to Slack” and “Add to Discord” flows.

## Honest limits

- The synthetic benchmark's rules and thresholds were tuned on that scenario, which has two planted drifts: its 1.00 is an upper bound, not a production number.
- On real text, extraction is conservative and noisy (see above); the real-data labels were made by the AI assistant and only partly re-checked ([`docs/LABEL_RECHECK.md`](docs/LABEL_RECHECK.md)).
- The impact-analysis organisation data and the HR records are hand-written demo data; project status changes are read from chat with a keyword rule.
- Jira and Linear are tested against fake APIs only; Google Drive likewise. There is no sign-in: a team's dashboard link is its key.


## Project map

- `connectors/` — source adapters and event normalization
- `pipeline/` — ingestion, extraction, resolution, access, webhooks, and actions
- `graph/` — FalkorDB connection, writers, schema, and Cypher queries
- `agent/` — tools, routing, Q&A, retros, and spec generation
- `bots/` — Slack, Discord, and daily digest
- `api/` — FastAPI service, integrations, metrics, and SSE
- `web/` — React dashboard
- `benchmark/`, `tests/`, `docs/` — measurements, regression coverage, and technical notes

For architecture, setup details, query explanations, and complete results, see [`docs/DETAILS.md`](docs/DETAILS.md), [`docs/EXPLAIN.md`](docs/EXPLAIN.md), [`docs/QUERIES.md`](docs/QUERIES.md), and [`docs/RESULTS.md`](docs/RESULTS.md).

## AI assistant disclosure

Built with help from an AI coding assistant (Claude Code), as the hackathon rules allow. The idea, the scenario and the graph model come from our project plan, and we can explain every part ([`docs/EXPLAIN.md`](docs/EXPLAIN.md)). The real-data labels were made by the assistant and are marked as such.
