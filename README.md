# Context Graph Drift Monitor

> Graph Hacks: Context for AI Agents (WeMakeDevs x FalkorDB), **Company Brain** track.

Decisions get made in chat, requirements live in tickets, and code ships in pull requests, but none of the three are linked. This project builds a context graph in FalkorDB that ties Slack/Discord messages, tickets and GitHub PRs to the same feature. It uses that graph to:

1. **Sprint retro report**: what we decided, what we shipped, and where the two diverge.
2. **Live drift alerts**: when a chat message changes a requirement that the ticket or PR doesn't reflect, an alert is posted with the graph path as evidence.
3. **Cited Q&A**: every answer shows the graph path behind it.
4. **Spec generation**: turns a drifted feature's graph context into a spec an agent can work from.

_Status: work in progress._

## Architecture

```
Slack / Discord / GitHub / mock tickets
        │  connectors/  (common event format)
        ▼
pipeline/  extraction (DeepSeek) → entity resolution → graph write
        ▼
FalkorDB Cloud  (one graph per organisation)
        ▼
api/ (FastAPI) ── agent/ (graph tools + DeepSeek) ── drift monitor ── frontend/
```

| Folder | Purpose |
|---|---|
| `connectors/` | Slack, Discord, GitHub, mock-ticket ingestion |
| `pipeline/` | Extraction, entity resolution, graph writes |
| `graph/` | Schema, Cypher queries, DB connection |
| `agent/` | Graph tools and the answering agent |
| `api/` | FastAPI backend for the dashboard and bots |
| `frontend/` | Dashboard |
| `data/` | Synthetic scenario, mock tickets, answer key |
| `benchmark/` | Questions answered with the graph vs. without it |
| `docs/` | Design notes |

## Graph data model

See [`graph/schema.cypher`](graph/schema.cypher). _(Diagram and properties to follow.)_

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in credentials
python -m scripts.check_setup
```

`check_setup` checks FalkorDB, Slack, Discord, GitHub and DeepSeek one by one and prints PASS/FAIL for each.

## Data

All data is synthetic or owned by the author: a Slack workspace and Discord server filled with synthetic conversations, a public GitHub repo owned by the author, and mock Linear-style tickets. No private or personal data is used.

## Limitations and future work

_To be filled in._ Out of scope: Notion, Gong, real Linear/Jira connectors, a learning loop, agents executing the specs, and real-time entity resolution at company scale.

## AI assistant disclosure

This project was built with help from an AI coding assistant (Claude Code). The graph model, queries and architecture are my own, and I can explain each part.
