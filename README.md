# Drift Monitor

> **A context graph for decisions that never made it into the work.**

Drift Monitor, also called **Company Brain**, connects Slack, Discord, tickets, GitHub pull requests, and documents in one FalkorDB graph. It answers cross-system questions and catches the gap between *what a team decided* and *what the team shipped*.

![Drift Monitor landing page](docs/screenshot-hero.png)

## The problem

A product decision usually happens in a conversation. The ticket keeps yesterday's requirement, the PR implements the old scope, and the PRD is stale. Keyword search can find each item, but cannot reliably determine version order, implementation coverage, or who can resolve the mismatch.

Drift Monitor builds the missing context. A message can change a requirement; a requirement amends a ticket; a pull request implements a particular requirement version; a document mentions the ticket; and every edge retains enough provenance to explain the result. The dashboard exposes the evidence path instead of returning an unsupported summary.

## What it does

- **Detects requirement drift.** A chat change is open drift when it is still the newest requirement, no PR implements it, and nobody explicitly kept the old scope.
- **Shows the evidence.** Each alert includes the author, source channel, previous requirement, affected ticket, stale PRs, and stale documents.
- **Answers graph questions.** Ask who decided something, what replaced it, who knows the most, how two entities are connected, or which work and client deliverables depend on a delayed project.
- **Answers across systems.** *"Why is the database migration delayed, and who can approve an override?"* follows a Slack message to a Notion doc, the doc to its ticket (BD-116), the ticket to its assignee, and the HR record to their manager, with a source badge per system. Project status also changes live: a lead's *"We are cancelling Project Gamma"* updates the graph, with that message as evidence.
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

The Slack bot uses Socket Mode and posts alerts in the originating thread. Discord is supported through a gateway bot. GitHub pull-request webhooks, ticket-style webhooks, document webhooks, and Google Drive change notifications can all trigger incremental updates. Tokens stay server-side; installation records are kept in the ignored `data/installs.json` file. Every workspace or server that connects through those buttons gets its own private graph, so it never mixes with the demo company or another team; connecting a new team's tickets and pull requests is not self-serve yet.

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

For real Slack or Discord data, add the relevant bot credentials to `.env` and follow [`docs/REAL_RUN.md`](docs/REAL_RUN.md). The web overview also provides consent-based “Add to Slack” and “Add to Discord” flows.

## Validation and honest boundaries

The repository includes unit, API, connector, graph, access-control, paging, integration, and benchmark tests. CI runs Ruff, mypy, the suite, an ablation gate, and query-plan checks. On the synthetic benchmark, the full graph reaches 1.00 precision and recall for drift; removing version reasoning drops precision to 0.50. A 22,940-node stress test finds 100 of 100 planted drifts with zero false positives.

Those results are an upper bound: rules and thresholds were tuned on the synthetic scenario, which contains two real drifts. Real-text extraction is conservative; Google Drive is tested against a fake API; impact-analysis organisation data and the HR records are hand-written demo data; and project status changes are read from chat with a keyword rule, not a model. The project makes uncertainty and evidence visible rather than pretending a benchmark replaces production calibration.

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
