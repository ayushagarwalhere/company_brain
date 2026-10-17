# The decision was made in Slack. The ticket never heard about it.

*How I built a company-brain agent on FalkorDB that catches decisions that never shipped, and then gets them shipped. Built for Graph Hacks (WeMakeDevs × FalkorDB).*

Here is a bug that never shows up in a stack trace.

On 22 September, the product manager writes in `#support-escalations`: *"the export must support any custom date range up to 12 months, and include all custom fields."* Everyone agrees. Nobody updates ticket BD-101, which still says *"last 30 days as CSV"*. Three days later a pull request ships exactly what the ticket says. The PRD still describes the old version too. The code matches the ticket, the ticket matches the docs, and all three are wrong.

I call this **drift**: a decision made in chat that nothing newer replaced, no PR implemented and nobody chose to drop. It's a relationship problem, not a lookup problem, so I modelled it as a graph.

## The model: versions are nodes

The key choice was to make every version of a requirement its own node. A ticket's description is a `Requirement`; so is each change decided in chat. Time-ordered `SUPERSEDES` edges link them, and pull requests point at the version they `IMPLEMENT`:

```
(Person maya)-[:POSTED]->(Message)-[:CHANGES]->(Requirement "12 months + custom fields")
   -[:AMENDS]->(Ticket BD-101)-[:ABOUT]->(Feature "Ticket CSV export")
(PullRequest #6)-[:IMPLEMENTS]->(Requirement "last 30 days")   ← the older version
```

Drift is then one Cypher query with three anti-patterns:

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)   // still the newest version
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)   // nothing shipped it
  AND NOT (:Decision)-[:DISMISSES]->(r)       // nobody chose to keep the old scope
```

The same query collects the evidence: who decided, where, which PRs and docs are still on the old version. Every alert carries that path, so nobody has to trust the bot. They can read why it fired.

## Where the graph earns its keep

I tried hard to prove the graph *wasn't* needed. I gave a SQLite database the same extracted facts and the same version chain, and an anti-join found exactly the same drift. So I'm not claiming a faster join. What the graph gave me was everything around the join:

- **Context that IDs miss.** The decisive messages never name a ticket. They're replies in a thread, or a PM talking about "the export". Threads (`REPLY_TO`), people and time connect them. With ticket IDs alone, both real drifts in my test company were missed.
- **Version reasoning.** Switch off `SUPERSEDES`/`IMPLEMENTS` and half the alerts become false. CI runs that ablation and fails the build if it regresses.
- **Multi-hop answers.** "How is the support agent connected to PR #6?" is `algo.SPpaths`: liam's message → maya's reply in the thread → BD-101 ← PR #6. Four hops, returned *with* the answer.
- **Who owns what.** Ticket creators and assignees, PR and doc authors, and who is most involved in a feature are all edges, which matters for the next part.

## From alert to action

An alert that says "this is wrong" is only half useful. The agent also closes the loop, in the thread where the alert appeared:

```
maya:  @Drift Monitor plan
bot:   1. Write the decision into BD-102 (done by me when an owner approves)
       2. Change PR #7 "Add export button to ticket list" → kenji
       3. Update DOC-1 "PRD — Ticket export" → maya
       Also tell: sofia, arjun, liam. Who can approve: Maya Chen or Kenji Watanabe.
zara:  @Drift Monitor fix it
bot:   🔒 Only BD-102's owners can decide this: Maya Chen or Kenji Watanabe.
maya:  @Drift Monitor fix it
bot:   ✅ Done. BD-102 now carries the decision. Follow-ups: T-1 → kenji, T-2 → maya
```

The plan is a graph read: `AUTHORED` tells it who wrote the stale PR and doc, `ASSIGNED_TO` and `AUTHORED` on the ticket tell it who may decide. Approving writes the decision as the ticket's next version and opens follow-up `Task` nodes linked to the approver, the assignee, the PR or doc they fix, and the decision they serve. Those human-made nodes survive every rebuild of the derived graph, so the agent's memory is just more graph.

## Guardrails I'd use again

Following FalkorDB's own advice on graph agents:

1. **Fixed tools, not text-to-Cypher.** I write the Cypher; the model picks one of 11 tools and fills typed arguments.
2. **Read-only by construction.** Every tool runs on `GRAPH.RO_QUERY`. The agent physically can't write; only an owner's approval does.
3. **Post-generation check.** If the model's answer names a ticket or PR that no tool returned, the answer is thrown away and replaced by the grounded one. A small model once invented `BD-123`; that's the bug this catches.
4. **"Not in the graph" is an answer.** "Is BD-999 stale?" gets "I couldn't find BD-999 in the graph", not a guess.

## What the numbers say, including the bad ones

- **Synthetic company** (300 messages): drift precision and recall 1.00. I wrote the rules while looking at that data, so treat that as an upper bound.
- **Scale:** 100 of 100 planted drifts found in a 22,940-node graph; whole-graph drift query p50 39 ms.
- **Q&A:** with a strong model (gpt-oss-120b), the graph agent scored 0.84 against 0.71 for retrieval feeding the same model. With no LLM at all, plain retrieval that dumps 25 passages beats my rules agent (0.98 vs 0.86) at five times the length.
- **Real GitHub text is the weak link.** The rules extractor's drift flags were all false on two public repos. A strong model fixed the false positives but still found only 2 of 7 real decisions.
- **It runs for real.** A decision posted in a real Slack workspace got an in-thread alert within seconds, and a real merged PR on GitHub closed a drift through `IMPLEMENTS`.

## What I learned

1. **Model the question, not the data.** "Did we ship what we decided?" made versions-as-nodes obvious. Everything else followed.
2. **Measure against the boring baseline.** The SQL comparison hurt, and it made the pitch sharper: the value is the model, the evidence and the actions, not raw query speed.
3. **An agent should end at a decision made by a person.** The bot proposes; the owner approves; the graph remembers who did what.

Code, results and the full list of weaknesses: **https://github.com/ayushagarwalhere/company_brain**
