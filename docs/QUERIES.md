# Cypher queries the product depends on

_Generated from [`graph/queries.py`](../graph/queries.py) by `python -m scripts.export_queries`._

Run them in the FalkorDB Browser (http://localhost:3001) against the `company_brain` graph; parameters are written `$name`.

## Drift, in words

```
The Cypher queries the product depends on. Each is documented in the README.

Drift definition (time-ordered path query):
  A requirement R is DRIFTED when
    - R came from chat:      (Message)-[:CHANGES]->(R)-[:AMENDS]->(Ticket)
    - R is still current:    nothing SUPERSEDES R (no newer ticket version or chat change for that ticket)
    - no PR delivers it:     NOT (PullRequest)-[:IMPLEMENTS]->(R)
    - nobody dismissed it:   NOT (Decision)-[:DISMISSES]->(R)   ("keep the old scope")
  Evidence = the message path, the stale ticket text, PRs on the same ticket
  (which, by the last condition, implement an older requirement or none), and docs
  mentioning the ticket that were last updated before the change (stale docs).
```

## Index

- [`DRIFT`](#drift): The core query: chat-originated requirements that are still current, unimplemented and not dismissed, with evidence.
- [`SPRINT_DECISIONS`](#sprint_decisions): Retro: per sprint, what was decided, what shipped, where they diverge
- [`SPRINT_SHIPPED`](#sprint_shipped): Retro: PRs merged in the sprint, their tickets, how each link was resolved, and which requirement they implement
- [`FEATURE_TIMELINE`](#feature_timeline): Chronological messages, tickets, PRs and requirements attached to a feature
- [`DECISION_HISTORY`](#decision_history): How a feature's requirements evolved: each version, its source (ticket or chat), what it supersedes, which PRs implement it
- [`WHO_KNOWS`](#who_knows): Who knows a topic: people connected to the feature through anything they wrote, weighted by kind (a decision or PR counts more than a chat message).
- [`DECISION_IMPACT`](#decision_impact): Impact: everything reachable downstream of a decision (requirement -> ticket -> PRs, people)
- [`CONNECTION`](#connection): How are two things connected? FalkorDB's algo.SPpaths finds the shortest path with relDirection 'both' (Cypher shortestPath is directed-only in FalkorDB). An earlier version enumerated every undirected path up to 7 hops and sorted them, which timed out at ~24k messages (benchmark/scale.py); SPpaths answers the same question in milliseconds. ABOUT is left out on purpose: going through the Feature hub is always short and explains nothing. __LA__ / __LB__ are replaced by labels from label_of() (whitelisted), so both endpoints come from an index seek.
- [`ORPHAN_PRS`](#orphan_prs): Coverage: merged work that no ticket explains
- [`DONE_WITHOUT_PR`](#done_without_pr): Coverage: tickets closed as Done with no PR referencing them
- [`UNDISCUSSED_TICKETS`](#undiscussed_tickets): Coverage: tickets no chat message ever mentions
- [`UNVERIFIED_CHANGES`](#unverified_changes): Unverified changes: a chat message that reads as a requirement change, from someone who doesn't own the ticket it was matched to, where that ticket was only a text-similarity guess. Kept visible instead of dropped; never counted as drift.
- [`KNOWLEDGE_RISK`](#knowledge_risk): Knowledge concentration ("bus factor"): share of a feature's weighted involvement held by its top person
- [`FEATURE_EVENTS`](#feature_events): Everything on a feature's time axis: requirement versions (ticket + chat) and PRs
- [`DRIFT_FOR_TICKET`](#drift_for_ticket): Same query anchored on one ticket: starts from the Requirement(ticket) index instead of a label scan

## DRIFT

The core query: chat-originated requirements that are still current, unimplemented and not dismissed, with evidence.

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)
  AND NOT (:Decision)-[:DISMISSES]->(r)
  AND ($feature IS NULL OR f.id = $feature)
  AND ($ticket IS NULL OR t.id = $ticket)
MATCH (author:Person)-[:POSTED]->(m)
OPTIONAL MATCH (r)-[:SUPERSEDES]->(prev:Requirement)
OPTIONAL MATCH (d:Decision)-[:CHANGES]->(r)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(old:Requirement)
OPTIONAL MATCH (doc:Document)-[:MENTIONS]->(t) WHERE doc.updated_ms < r.at_ms
RETURN f.id AS feature, f.name AS feature_name, t.id AS ticket, t.title AS ticket_title, t.url AS ticket_url,
       t.description AS ticket_text, t.desc_updated_ms AS ticket_updated_ms,
       r.id AS requirement, r.text AS requirement_text, r.at AS changed_at,
       m.id AS message, m.text AS message_text, m.url AS message_url, m.source AS source, m.channel AS channel,
       author.id AS changed_by, d.id AS decision,
       prev.text AS previous_requirement,
       r.at_ms AS changed_ms,
       collect(DISTINCT {pr: pr.number, title: pr.title, url: pr.url, merged: pr.merged,
                         merged_after: coalesce(pr.merged_ms, pr.created_ms) > r.at_ms,
                         implements: old.text}) AS stale_prs,
       collect(DISTINCT {id: doc.id, title: doc.title, updated: doc.updated, url: doc.url}) AS stale_docs
ORDER BY changed_ms
```

Used by: [`agent/retro.py`](../agent/retro.py), [`agent/tools.py`](../agent/tools.py), [`api/main.py`](../api/main.py), [`benchmark/noise.py`](../benchmark/noise.py), [`benchmark/real_data.py`](../benchmark/real_data.py), [`benchmark/scale.py`](../benchmark/scale.py), [`benchmark/score_resolution.py`](../benchmark/score_resolution.py), [`benchmark/sql_baseline.py`](../benchmark/sql_baseline.py), [`bots/commands.py`](../bots/commands.py), [`bots/digest.py`](../bots/digest.py), [`graph/explore.py`](../graph/explore.py), [`pipeline/actions.py`](../pipeline/actions.py), [`pipeline/build.py`](../pipeline/build.py), [`pipeline/impact.py`](../pipeline/impact.py), [`pipeline/live.py`](../pipeline/live.py), [`pipeline/webhooks.py`](../pipeline/webhooks.py), [`pipeline/work.py`](../pipeline/work.py)

## SPRINT_DECISIONS

Retro: per sprint, what was decided, what shipped, where they diverge

```cypher
MATCH (s:Sprint {id: $sprint})
MATCH (p:Person)-[:MADE]->(d:Decision)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
WHERE d.at_ms >= s.start_ms AND d.at_ms <= s.end_ms
MATCH (d)-[:RECORDED_IN]->(m:Message)
OPTIONAL MATCH (r)-[:ABOUT]->(f:Feature)
OPTIONAL MATCH (newer:Requirement)-[:SUPERSEDES]->(r)
OPTIONAL MATCH (impl:PullRequest)-[:IMPLEMENTS]->(r)
OPTIONAL MATCH (impl2:PullRequest)-[:IMPLEMENTS]->(newer)
OPTIONAL MATCH (dis:Decision)-[:DISMISSES]->(r)
OPTIONAL MATCH (disby:Person)-[:MADE]->(dis)
RETURN d.id AS decision, disby.id AS dismissed_by, d.text AS text, d.at AS at, p.id AS by, t.id AS ticket, f.name AS feature,
       m.url AS source, m.source AS platform, m.channel AS channel,
       newer.origin AS superseded_by, collect(DISTINCT impl.number) + collect(DISTINCT impl2.number) AS shipped_in,
       d.at_ms AS at_ms
ORDER BY at_ms
```

Used by: [`agent/retro.py`](../agent/retro.py)

## SPRINT_SHIPPED

Retro: PRs merged in the sprint, their tickets, how each link was resolved, and which requirement they implement

```cypher
MATCH (s:Sprint {id: $sprint})<-[:IN_SPRINT]-(pr:PullRequest)
WHERE pr.merged_ms IS NOT NULL
MATCH (a:Person)-[:AUTHORED]->(pr)
OPTIONAL MATCH (pr)-[ref:REFERENCES]->(t:Ticket)
OPTIONAL MATCH (pr)-[:ABOUT]->(f:Feature)
OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(r:Requirement)
RETURN pr.number AS pr, pr.title AS title, pr.url AS url, pr.merged AS merged, a.id AS author,
       collect(DISTINCT t.id) AS tickets, collect(DISTINCT coalesce(ref.how, 'hard')) AS link,
       f.name AS feature, collect(DISTINCT r.id) AS implements, pr.merged_ms AS merged_ms
ORDER BY merged_ms
```

Used by: [`agent/retro.py`](../agent/retro.py)

## FEATURE_TIMELINE

Chronological messages, tickets, PRs and requirements attached to a feature

```cypher
MATCH (f:Feature {id: $feature})
MATCH (x)-[:ABOUT]->(f)
WHERE x:Message OR x:Ticket OR x:PullRequest OR x:Requirement
WITH x, coalesce(x.ts_ms, x.at_ms, x.merged_ms, x.created_ms) AS at
OPTIONAL MATCH (p:Person)-[:POSTED|AUTHORED]->(x)
RETURN labels(x)[0] AS type, x.id AS id, coalesce(x.text, x.title) AS text, at,
       coalesce(x.url, '') AS url, p.id AS person
ORDER BY at
```

Used by: [`agent/tools.py`](../agent/tools.py)

## DECISION_HISTORY

How a feature's requirements evolved: each version, its source (ticket or chat), what it supersedes, which PRs implement it

```cypher
MATCH (f:Feature {id: $feature})<-[:ABOUT]-(t:Ticket)
MATCH (r:Requirement {ticket: t.id})
OPTIONAL MATCH (src)-[:STATES|CHANGES]->(r)
OPTIONAL MATCH (r)-[:SUPERSEDES]->(prev:Requirement)
OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(r)
RETURN t.id AS ticket, r.id AS requirement, r.text AS text, r.at AS at, r.origin AS origin,
       labels(src)[0] AS source_type, src.id AS source_id, coalesce(src.url, '') AS source_url,
       prev.id AS supersedes, collect(DISTINCT pr.number) AS implemented_by, r.at_ms AS at_ms
ORDER BY ticket, at_ms
```

Used by: [`agent/tools.py`](../agent/tools.py)

## WHO_KNOWS

Who knows a topic: people connected to the feature through anything they wrote, weighted by kind (a decision or PR counts more than a chat message).

```cypher
MATCH (f:Feature {id: $feature})
MATCH (p:Person)-[rel:POSTED|AUTHORED|MADE]->(x)
WHERE (x)-[:ABOUT]->(f) OR (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f)
WITH p, x, CASE WHEN x:Decision THEN 5 WHEN x:PullRequest THEN 4 WHEN x:Ticket THEN 3 ELSE 1 END AS w
RETURN p.id AS person, p.name AS name, p.role AS role, sum(w) AS score, count(x) AS items
ORDER BY score DESC
```

Used by: [`agent/tools.py`](../agent/tools.py), [`pipeline/work.py`](../pipeline/work.py)

## DECISION_IMPACT

Impact: everything reachable downstream of a decision (requirement -> ticket -> PRs, people)

```cypher
MATCH (d:Decision {id: $decision})-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(owner:Person)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (other:Ticket)-[:ABOUT]->(:Feature)<-[:ABOUT]-(t) WHERE other <> t
RETURN d.text AS decision, t.id AS ticket, owner.id AS owner,
       collect(DISTINCT pr.number) AS prs, collect(DISTINCT other.id) AS related_tickets
```

Used by: [`agent/tools.py`](../agent/tools.py)

## CONNECTION

How are two things connected? FalkorDB's algo.SPpaths finds the shortest path with relDirection 'both' (Cypher shortestPath is directed-only in FalkorDB). An earlier version enumerated every undirected path up to 7 hops and sorted them, which timed out at ~24k messages (benchmark/scale.py); SPpaths answers the same question in milliseconds. ABOUT is left out on purpose: going through the Feature hub is always short and explains nothing. __LA__ / __LB__ are replaced by labels from label_of() (whitelisted), so both endpoints come from an index seek.

```cypher
MATCH (a:__LA__ {id: $a}), (b:__LB__ {id: $b})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: 7, pathCount: 1,
                   relTypes: ['POSTED', 'REPLY_TO', 'CHANGES', 'AMENDS', 'STATES', 'REFERENCES', 'IMPLEMENTS', 'MADE',
                              'AUTHORED', 'ASSIGNED_TO', 'SUPERSEDES', 'MENTIONS', 'RECORDED_IN']})
YIELD path
RETURN [n IN nodes(path) | {id: n.id, type: labels(n)[0]}] AS nodes, [r IN relationships(path) | type(r)] AS rels,
       [r IN relationships(path) | startNode(r).id] AS starts, length(path) AS hops
```

## ORPHAN_PRS

Coverage: merged work that no ticket explains

```cypher
MATCH (a:Person)-[:AUTHORED]->(pr:PullRequest)
WHERE NOT (pr)-[:REFERENCES]->(:Ticket)
RETURN pr.number AS pr, pr.title AS title, pr.url AS url, a.id AS author, pr.merged AS merged ORDER BY pr
```

Used by: [`api/main.py`](../api/main.py), [`bots/digest.py`](../bots/digest.py)

## DONE_WITHOUT_PR

Coverage: tickets closed as Done with no PR referencing them

```cypher
MATCH (t:Ticket) WHERE t.state = 'Done' AND NOT (:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person)
RETURN t.id AS ticket, t.title AS title, p.id AS owner ORDER BY ticket
```

Used by: [`api/main.py`](../api/main.py), [`bots/digest.py`](../bots/digest.py)

## UNDISCUSSED_TICKETS

Coverage: tickets no chat message ever mentions

```cypher
MATCH (t:Ticket) WHERE NOT (:Message)-[:MENTIONS]->(t)
OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
RETURN t.id AS ticket, t.title AS title, t.state AS state, f.name AS feature ORDER BY ticket
```

Used by: [`api/main.py`](../api/main.py)

## UNVERIFIED_CHANGES

Unverified changes: a chat message that reads as a requirement change, from someone who doesn't own the ticket it was matched to, where that ticket was only a text-similarity guess. Kept visible instead of dropped; never counted as drift.

```cypher
MATCH (p:Person)-[:POSTED]->(m:Message)-[:SUGGESTS]->(q:Requirement {status: 'candidate'})-[:MAY_AMEND]->(t:Ticket)
RETURN q.id AS id, q.text AS text, q.at AS at, m.id AS message, m.source AS source, m.channel AS channel,
       p.id AS author, t.id AS ticket, t.title AS ticket_title ORDER BY q.at_ms DESC
```

Used by: [`api/main.py`](../api/main.py)

## KNOWLEDGE_RISK

Knowledge concentration ("bus factor"): share of a feature's weighted involvement held by its top person

```cypher
MATCH (f:Feature)
MATCH (p:Person)-[:POSTED|AUTHORED|MADE]->(x)
WHERE (x)-[:ABOUT]->(f) OR (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f)
WITH f, p, sum(CASE WHEN x:Decision THEN 5 WHEN x:PullRequest THEN 4 WHEN x:Ticket THEN 3 ELSE 1 END) AS w
ORDER BY w DESC
WITH f, collect({person: p.id, name: p.name, w: w}) AS people, sum(w) AS total
RETURN f.id AS feature, f.name AS name, people[0].name AS top_person, people[0].w * 1.0 / total AS top_share,
       size(people) AS people, total
ORDER BY top_share DESC
```

Used by: [`api/main.py`](../api/main.py), [`bots/digest.py`](../bots/digest.py)

## FEATURE_EVENTS

Everything on a feature's time axis: requirement versions (ticket + chat) and PRs

```cypher
MATCH (f:Feature {id: $feature})
CALL {
  WITH f
  MATCH (t:Ticket)-[:ABOUT]->(f), (t)-[:STATES]->(r:Requirement)
  RETURN 'ticket' AS lane, r.id AS id, r.at_ms AS at, t.id + ' updated' AS title, r.text AS text, t.id AS ref, null AS who
  UNION
  WITH f
  MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:ABOUT]->(f), (p:Person)-[:POSTED]->(m)
  RETURN 'chat' AS lane, r.id AS id, r.at_ms AS at, m.source + ' #' + m.channel AS title, r.text AS text, r.ticket AS ref, p.id AS who
  UNION
  WITH f
  MATCH (d:Document)-[:ABOUT]->(f), (a:Person)-[:AUTHORED]->(d)
  RETURN 'doc' AS lane, d.id AS id, d.updated_ms AS at, d.title AS title, d.text AS text, d.id AS ref, a.id AS who
  UNION
  WITH f
  MATCH (pr:PullRequest)-[:ABOUT]->(f), (a:Person)-[:AUTHORED]->(pr)
  RETURN 'pr' AS lane, pr.id AS id, coalesce(pr.merged_ms, pr.created_ms) AS at, 'PR #' + toString(pr.number) AS title,
         pr.title AS text, null AS ref, a.id AS who
}
RETURN lane, id, at, title, text, ref, who ORDER BY at
```

Used by: [`api/main.py`](../api/main.py)

## DRIFT_FOR_TICKET

Same query anchored on one ticket: starts from the Requirement(ticket) index instead of a label scan

```cypher
MATCH (r:Requirement {ticket: $ticket})
MATCH (m:Message)-[:CHANGES]->(r)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)
  AND NOT (:Decision)-[:DISMISSES]->(r)
  AND ($feature IS NULL OR f.id = $feature)
  AND ($ticket IS NULL OR t.id = $ticket)
MATCH (author:Person)-[:POSTED]->(m)
OPTIONAL MATCH (r)-[:SUPERSEDES]->(prev:Requirement)
OPTIONAL MATCH (d:Decision)-[:CHANGES]->(r)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(old:Requirement)
OPTIONAL MATCH (doc:Document)-[:MENTIONS]->(t) WHERE doc.updated_ms < r.at_ms
RETURN f.id AS feature, f.name AS feature_name, t.id AS ticket, t.title AS ticket_title, t.url AS ticket_url,
       t.description AS ticket_text, t.desc_updated_ms AS ticket_updated_ms,
       r.id AS requirement, r.text AS requirement_text, r.at AS changed_at,
       m.id AS message, m.text AS message_text, m.url AS message_url, m.source AS source, m.channel AS channel,
       author.id AS changed_by, d.id AS decision,
       prev.text AS previous_requirement,
       r.at_ms AS changed_ms,
       collect(DISTINCT {pr: pr.number, title: pr.title, url: pr.url, merged: pr.merged,
                         merged_after: coalesce(pr.merged_ms, pr.created_ms) > r.at_ms,
                         implements: old.text}) AS stale_prs,
       collect(DISTINCT {id: doc.id, title: doc.title, updated: doc.updated, url: doc.url}) AS stale_docs
ORDER BY changed_ms
```

## Also used

- **Full-text search** ([`graph/explore.py`](../graph/explore.py)): `CALL db.idx.fulltext.createNodeIndex('Message', 'text')` (plus Ticket, PullRequest, Person) and `CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score`.
- **Writes** ([`graph/writer.py`](../graph/writer.py), [`pipeline/resolve.py`](../pipeline/resolve.py), [`pipeline/actions.py`](../pipeline/actions.py)): every node is `MERGE`d on `id` (idempotent re-ingest); resolution edges carry `via` so each link records how it was made.
- **Graph algorithm**: the connection tool uses `algo.SPpaths` with `relDirection: 'both'`, because Cypher `shortestPath` is directed-only in FalkorDB (see [`EXPLAIN.md`](EXPLAIN.md)).
