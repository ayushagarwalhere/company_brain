# Devpost submission: Context Graph Drift Monitor

## Project name
Context Graph Drift Monitor

## Tagline (elevator pitch)
Catches the moment a decision made in Slack or Discord stops matching the ticket and the code, and shows the exact graph path that proves it.

## Inspiration
Every team I've seen loses work the same way. A requirement changes in a chat thread ("let's do 12 months, not 30 days"), everyone in the thread agrees, and the ticket is never updated. Two weeks later a PR ships the old version, and nobody notices until a customer does. The information existed; it was just spread across three tools that don't know about each other.

## What it does
It builds a **context graph** (FalkorDB) that links chat messages, tickets and GitHub pull requests to the same feature and the same requirement, then:

- **Live drift alerts:** when a new Slack or Discord message changes a requirement that the ticket or PRs don't reflect, the bot replies in the thread with the evidence, for example: *Maya's message → changes requirement → amends BD-101 → PR #6 implements the older version*.
- **Sprint retro:** what we decided, what we shipped, and where they diverge, with a source link on every line.
- **Ask the graph:** an LLM agent answers questions using 8 graph tools (drift, decision history, timeline, who-knows, impact, how-connected…), and every answer lists the graph paths it used.
- **Spec generation:** turns a drifted feature's graph context into an agent-ready spec (it stops at the spec; nothing auto-executes).
- **Dashboard:** drift cards with before/after diffs, an interactive feature graph, the retro, and a "simulate a message" box that runs the live monitor.

## How we built it
- **Connectors** (Python) for Slack, Discord, the GitHub REST API and Linear-style ticket JSON all emit one common event format.
- **Graph model in FalkorDB:** Person, Message, Ticket, PullRequest, Feature, Requirement, Decision, Sprint, Alert. The key relationships are `CHANGES`, `AMENDS`, `STATES`, `SUPERSEDES` and `IMPLEMENTS`. Each ticket description version is its own Requirement node, so drift is judged against what the ticket said *at that time*.
- **Entity resolution in three steps**, and each link records how it was made: (1) hard links like "Fixes BD-101", (2) graph proximity (thread replies; a PR matched to tickets owned by its author that were open at that time), (3) semantic matching (LLM, with a TF-IDF fallback).
- **Drift is a time-ordered path query:** a requirement that came from chat, that nothing newer supersedes, and that no PR implements. A ticket edit only counts as superseding a chat change if its text actually reflects that change, so unrelated edits can't hide drift.
- **Stack:** DeepSeek (OpenAI-compatible API) for extraction and the tool-calling agent; FastAPI backend; plain HTML/JS dashboard with Cytoscape.js; Slack Bolt (Socket Mode) and discord.py bots; pytest.
- **Data:** a fully synthetic company (Brightdesk: 8 people, 2 sprints, 300 messages, 15 tickets, 12 PRs) with two planted drifts, one clean control feature, and deliberate traps: a change that *was* written back into the ticket, a rejected proposal, a "keep it as is" reaffirmation, and a PR with no ticket reference. An answer key records every expected link, and all scoring uses it.

## Challenges we ran into
- **Telling a decision apart from a suggestion.** "Should we also do XLSX?" followed by "not this quarter" must not count as a change, and the scenario plants exactly these traps.
- **Linking a PR that never mentions its ticket.** We solved it with graph proximity: who wrote the PR, which of their tickets were open then, and what it's about.
- **Messages can't be backdated** in Slack, Discord or GitHub, so seeding writes a seed map and PR trailers that restore the original author and timestamp.
- **FalkorDB's `shortestPath` is directed-only**, so the "how are these connected" tool uses a bounded undirected search that skips the Feature hub, which would otherwise make every path trivially short.

## Accomplishments that we're proud of
- Every alert and answer comes with an explainable graph path, not just a score.
- On the synthetic dataset, the resolution and drift logic finds exactly the planted drifts and their stale PRs (precision and recall 1.00), correctly leaves the clean feature alone, and links the PR that has no ticket ID. *(These numbers come from the answer-key test harness, which checks the graph logic; LLM-extraction scores are in the README once run.)*
- 15 tests (unit and end-to-end on a throwaway graph), and re-ingesting is idempotent.

## What we learned
Most of the hard part is the data model, not the LLM. Once requirements are versioned nodes with `SUPERSEDES` and `IMPLEMENTS` edges, "did we ship what we decided?" becomes a short query, while plain retrieval over the same text finds the documents but can't tell which version is current.

## What's next
Real Linear and Jira connectors, a feedback loop on alerts (confirm or dismiss), vector indexes in FalkorDB for the semantic step, and letting coding agents pick up the generated specs.

## Built with
python, falkordb, cypher, deepseek, fastapi, javascript, cytoscape.js, slack-api, discord.py, github-api, pytest

## Links
- Code: https://github.com/ayushagarwalhere/company_brain
- Demo video: _add link_
- Live demo: _add link, or point to the README's local setup_
