# Devpost submission: Context Graph Drift Monitor

## Project name
Context Graph Drift Monitor

## Tagline (elevator pitch)
Catches the moment a decision made in Slack or Discord stops matching the ticket and the code, and shows the exact graph path that proves it.

## Inspiration
Every team I've seen loses work the same way. A requirement changes in a chat thread ("let's do 12 months, not 30 days"), everyone in the thread agrees, and the ticket is never updated. Two weeks later a PR ships the old version, and nobody notices until a customer does. The information existed; it was just spread across three tools that don't know about each other.

## What it does
It builds a **context graph** (FalkorDB) that links chat messages, product docs, tickets and GitHub pull requests to the same feature and the same requirement, then:

- **Live drift alerts:** when a new Slack or Discord message changes a requirement that the ticket or PRs don't reflect, the bot replies in the thread with the evidence, for example: *Maya's message → changes requirement → amends BD-101 → PR #6 implements the older version*.
- **Sprint retro:** what we decided, what we shipped, and where they diverge, with a source link on every line.
- **Ask the graph:** an LLM agent answers questions using 8 graph tools (drift, decision history, timeline, who-knows, impact, how-connected…), and every answer lists the graph paths it used.
- **Spec generation:** turns a drifted feature's graph context into an agent-ready spec (it stops at the spec; nothing auto-executes).
- **Coverage and risk:** PRs with no ticket, tickets closed without code, tickets nobody discussed, and features where one person holds most of the knowledge.
- **Close the loop:** one click writes the decided requirement into the ticket as its next version, or records a "keep the old scope" decision. Both are stored in the graph, and the drift clears.
- **Feature timeline:** ticket versions, chat changes and PRs on one time axis, with the stretch where the ticket and PRs never caught up shaded in.
- **Stays current on its own:** a ticket-tracker webhook and a signed GitHub PR webhook update the graph as work changes. A ticket edit that carries the decision clears the drift; a cosmetic edit doesn't. Every open dashboard gets the change instantly over Server-Sent Events.
- **Dashboard:** a React app with a real-time 3D hero (the context graph orbiting a planet), drift cards with before/after diffs and one-click fixes, an interactive feature graph and timeline, full-text search, person profiles, the retro, and a simulator for chat messages and ticket edits.

## Does the graph do real work?
An ablation study (`python -m benchmark.ablation`, deterministic, no LLM) switches graph capabilities off one at a time and scores against the answer key. Without version reasoning (`SUPERSEDES`/`IMPLEMENTS`) **half the drift alerts are false**: changes that were already written back into tickets get flagged. With ticket IDs only (no thread structure or semantic linking) **both real drifts are missed**, because the decisive messages never mention a ticket ID. Without threads, message linking recall drops from 0.92 to 0.77. Person/time proximity made no difference on this dataset, and I report that as-is.

## How we built it
- **Connectors** (Python) for Slack, Discord, the GitHub REST API and Linear-style ticket JSON all emit one common event format.
- **Graph model in FalkorDB:** Person, Message, Ticket, PullRequest, Feature, Requirement, Decision, Sprint, Alert. The key relationships are `CHANGES`, `AMENDS`, `STATES`, `SUPERSEDES` and `IMPLEMENTS`. Each ticket description version is its own Requirement node, so drift is judged against what the ticket said *at that time*.
- **Entity resolution in three steps**, and each link records how it was made: (1) hard links like "Fixes BD-101", (2) graph proximity (thread replies; a PR matched to tickets owned by its author that were open at that time), (3) semantic matching (LLM, with a TF-IDF fallback).
- **Drift is a time-ordered path query:** a requirement that came from chat, that nothing newer supersedes, and that no PR implements. A ticket edit only counts as superseding a chat change if its text actually reflects that change, so unrelated edits can't hide drift.
- **Stack:** FalkorDB (Cypher, full-text indexes); Python + FastAPI (REST, webhooks, Server-Sent Events); DeepSeek (OpenAI-compatible) for extraction and the tool-calling agent, with a rule-based extractor and rules agent as automatic fallbacks; React 18 + TypeScript + Vite, Framer Motion, three.js / React Three Fiber with custom GLSL shaders, Cytoscape.js; Slack Bolt (Socket Mode) and discord.py bots; pytest + GitHub Actions CI with a FalkorDB service container.
- **Data:** a fully synthetic company (Brightdesk: 8 people, 2 sprints, 300 messages, 15 tickets, 12 PRs) with two planted drifts, one clean control feature, and deliberate traps: a change that *was* written back into the ticket, a rejected proposal, a "keep it as is" reaffirmation, and a PR with no ticket reference. An answer key records every expected link, and all scoring uses it.

## Challenges we ran into
- **Telling a decision apart from a suggestion.** "Should we also do XLSX?" followed by "not this quarter" must not count as a change, and the scenario plants exactly these traps.
- **Linking a PR that never mentions its ticket.** We solved it with graph proximity: who wrote the PR, which of their tickets were open then, and what it's about.
- **Messages can't be backdated** in Slack, Discord or GitHub, so seeding writes a seed map and PR trailers that restore the original author and timestamp.
- **FalkorDB's `shortestPath` is directed-only**, so the "how are these connected" tool uses `algo.SPpaths` with `relDirection: 'both'` and skips the Feature hub, which would otherwise make every path trivially short. My first version enumerated every undirected path and timed out at scale.
- **Real text is much harder than my synthetic company.** On two public GitHub repos the rules extractor's drift flags were all false (0/25 labelled): it mistakes code review, status updates and volunteer proposals for decisions. Injecting 500 noise messages into the demo hid both real drifts. Decision rights (only a ticket's creator or assignee can change it from chat) cut false requirement changes by 71% but recovered nothing. The root cause turned out to be in the supersession chain: the latest misread message replaced the real decision. After fixing that, both drifts come back (2/2); with the rule extractor that costs 14 noise-caused false alerts. A small local LLM (qwen3:8b via Ollama) as the extractor lets almost none of the noise through: 1 noise-caused alert, both real drifts found. And a humbling one: given the same extracted facts and version chain, a plain SQLite join finds exactly the same drift as the graph. The value is in the version-chain reasoning, not in the database. All of this is in the README, numbers included.

## Accomplishments that we're proud of
- Every alert and answer comes with an explainable graph path, not just a score.
- With a rule-based extractor (no LLM, no answer key) the pipeline finds exactly the planted drifts and their stale PRs on the synthetic dataset (precision and recall 1.00), leaves the clean feature alone, and links the PR that has no ticket ID. *(I wrote the rules while looking at this dataset, so that's an upper bound; the LLM extractor is the general path.)*
- An ablation that switches graph capabilities off one at a time: without `SUPERSEDES`/`IMPLEMENTS`, half the drift alerts are false; with ticket IDs alone, both real drifts are missed.
- A stress test at about 60× the demo (20,800 messages): 100/100 planted drifts found, per-ticket drift check about 1 ms.
- Honest measurement: every number in the README comes with the command that produced it, including the bad ones.
- 88 tests (unit, end-to-end graph, HTTP API, connector contracts against fake Slack, Discord and GitHub APIs) run in CI against a pinned FalkorDB, with ruff, mypy and an ablation that fails the build if the graph stops doing the work.

## What we learned
Most of the hard part is the data model, not the LLM. Once requirements are versioned nodes with `SUPERSEDES` and `IMPLEMENTS` edges, "did we ship what we decided?" becomes a short query, while plain retrieval over the same text finds the documents but can't tell which version is current.

## What's next
Real Linear and Jira connectors, a feedback loop on alerts (confirm or dismiss), vector indexes in FalkorDB for the semantic step, and letting coding agents pick up the generated specs.

## Built with
python, falkordb, cypher, fastapi, server-sent-events, deepseek, react, typescript, vite, three.js, react-three-fiber, glsl, framer-motion, cytoscape.js, slack-api, discord.py, github-webhooks, pytest, github-actions

## Links
- Code: https://github.com/ayushagarwalhere/company_brain
- Demo video: _add link_
- Live demo: https://13-60-62-24.sslip.io/demo
- Try it on a GitHub repo: https://13-60-62-24.sslip.io/try/FalkorDB/FalkorDB
- MCP server for coding agents: https://13-60-62-24.sslip.io/mcp
