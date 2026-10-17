# Decided in chat, never shipped: catching requirement drift with a graph

*Built for Graph Hacks (WeMakeDevs × FalkorDB), Company Brain track. Code: https://github.com/ayushagarwalhere/company_brain*

Every team I've worked with loses work the same way. Someone posts in a Slack thread: "Acme needs a year of history, not 30 days, and their custom fields." Everyone in the thread agrees. Nobody updates the ticket. Two weeks later a pull request ships exactly what the ticket said, the 30-day export, and a customer is the one who notices.

The information existed. It was spread across chat, a ticket tracker, a PRD and GitHub, and none of those tools knows about the others. So I built **Drift Monitor**: a context graph in FalkorDB that ties messages, docs, tickets and pull requests to the same requirement, and flags the moment they disagree.

## The model is the product

My first instinct was "retrieve the relevant messages and ask an LLM if the ticket is stale". It falls apart quickly. Retrieval finds the documents, but it can't tell you which version of a requirement is *current*, or which version a PR actually *implements*. Those are questions about relationships and order, and that's what a graph is for.

The core of the model:

```
(Person)-[:POSTED]->(Message)-[:CHANGES]->(Requirement)-[:AMENDS]->(Ticket)
(Ticket)-[:STATES]->(Requirement)            // one node per description version
(Requirement)-[:SUPERSEDES]->(Requirement)   // per ticket, in time order
(PullRequest)-[:IMPLEMENTS]->(Requirement)
(Document)-[:MENTIONS]->(Ticket)
```

The key decision was making **every ticket description version its own `Requirement` node**. A ticket stops being a mutable blob of text and becomes a timeline you can query: what did it say on the 15th, and what did chat decide on the 22nd?

With that in place, drift is a short Cypher query:

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)   // still the newest word on this ticket
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)   // nothing shipped it
  AND NOT (:Decision)-[:DISMISSES]->(r)       // nobody chose to keep the old scope
RETURN f, t, r, m
```

Every alert carries the path that triggered it, so it's never "the AI thinks something's off". It reads like this:

`(Person maya)-[:POSTED]->(Message)-[:CHANGES]->(Requirement "12 months + custom fields")-[:AMENDS]->(Ticket BD-101) ; (PullRequest #6)-[:IMPLEMENTS]->(older "last 30 days")`

## Linking things that don't link themselves

The hard part wasn't the query. It was getting the edges right, because real teams don't reference ticket IDs consistently. I resolve links in three steps and record on each edge how it was made:

1. **Hard links.** "Fixes BD-101" in a PR, or a ticket ID in a message.
2. **Graph proximity.** A reply inherits its thread's feature. A PR with no ticket ID is matched against tickets *assigned to its author* that were *open at the time*.
3. **Semantic.** The LLM, or TF-IDF when there's no LLM.

The decisive messages in my scenario never mention a ticket ID. Maya's "Decision: the export must support any range up to 12 months" sits in a thread whose first message doesn't name BD-101 either. It's reachable only through the thread and what the thread is about.

## Does the graph actually do the work?

The hackathon rules say the graph must do real work, not sit on the side. So I measured it with an ablation study: rerun the whole pipeline with one graph capability switched off at a time, and score each run against a hand-written answer key. It's deterministic, needs no LLM, and anyone can rerun it with `python -m benchmark.ablation`.

| Configuration | Drift alerts P / R |
|---|---|
| Full graph | **1.00 / 1.00** |
| Without version reasoning (`SUPERSEDES` / `IMPLEMENTS`) | 0.50 / 1.00 |
| Ticket IDs only (no threads or semantic linking) | 1.00 / **0.00** |

Without version reasoning, **half the alerts are false**: changes that were already written back into their tickets get flagged again. With ticket IDs only, **both real drifts are missed**. One result surprised me: person/time proximity for PRs made *no* difference on this dataset, because the PR's text alone was enough. I kept that row in the README. An ablation that only shows wins isn't telling you much.

## Bugs that taught me something

- **"Fixed" is not a fix.** My rule-based check for "does this ticket edit reflect the chat change?" compared the words an edit *added* against the change. A test edit, "(typo fixed)", resolved a real drift, because the decision said "not a **fixed** 30 days". Now edit chatter doesn't count, and if the change states numbers (12 months, 15 minutes), the edit must contain one of them. I found this through an API test, not in production. That's the case for writing them.
- **FalkorDB's `shortestPath` is directed-only.** For "how is Liam connected to PR #6?" I needed an undirected search, so I used a bounded variable-length match over causal relationships. I deliberately left out `ABOUT`: going through the Feature hub is always short and explains nothing.
- **A valid key isn't a working LLM.** My DeepSeek key was valid but had no balance, so every call failed with a 402. The app now checks once whether the LLM answers, and falls back to the rule-based extractor and a rules agent that calls the same graph tools. Every answer says which path produced it.

## Keeping it current

A company brain that's only right at ingest time isn't much use. Two webhooks keep it current. A ticket edit becomes a new requirement version and re-runs the supersession check for that ticket. A signed GitHub PR webhook links the PR and decides which requirement version it implements. Changes stream to every open dashboard over Server-Sent Events, so when a PR that delivers the decision lands, the drift card disappears on its own.

## Where it breaks

I ran the unchanged pipeline on two public GitHub repos (FalkorDB and excalidraw). Every drift flag was wrong: 0 of 25 labelled items. The phrase rules fire on code review ("let's use a constant *instead of* the magic number"), status updates and "I'd like to work on this" offers. I also injected 500 messages that change nothing into the demo. The misread ones superseded the real decisions, and both real drifts disappeared. One principled fix, decision rights (only a ticket's creator or assignee can change it from chat), removed 71% of the false changes but brought neither drift back. Two later fixes changed that picture. A later message now replaces an open decision only when the extractor judges that it revises it, which brought both drifts back. And a small local model (qwen3:8b through Ollama) as the extractor let almost no noise through: one noise-caused alert in 500 messages.

The most useful result was the one against the graph: I loaded the same extracted facts into SQLite, and an anti-join over the same version chain found exactly the same drift, faster. The graph didn't make drift detection possible; the version-chain reasoning did. What the graph still gives me is the evidence path with every answer, variable-depth "how is X connected to Y" questions, and new node types without migrations. The README has every number and the command behind it, including the ones that went the wrong way.

## What I'd do next

Real Linear and Jira connectors, FalkorDB vector indexes for the semantic step, and a feedback loop where dismissing an alert teaches the extractor. The biggest lesson, though, was that **most of the hard part was the data model, not the model**. Once requirements were versioned nodes with `SUPERSEDES` and `IMPLEMENTS` edges, "did we ship what we decided?" stopped being a judgment call and became a query.

*The scenario is fully synthetic: a fictional helpdesk startup with 300 messages, 15 tickets, 12 PRs and 4 docs, with planted drifts, traps and an answer key. I built this with help from an AI coding assistant (Claude Code), and disclosed it as the rules require.*
