"""The Cypher queries the product depends on. Each is documented in the README.

Drift definition (time-ordered path query):
  A requirement R is DRIFTED when
    - R came from chat:      (Message)-[:CHANGES]->(R)-[:AMENDS]->(Ticket)
    - R is still current:    nothing SUPERSEDES R (no newer ticket version or chat change for that ticket)
    - no PR delivers it:     NOT (PullRequest)-[:IMPLEMENTS]->(R)
    - nobody dismissed it:   NOT (Decision)-[:DISMISSES]->(R)   ("keep the old scope")
  Evidence = the message path, the stale ticket text, PRs on the same ticket
  (which, by the last condition, implement an older requirement or none), and docs
  mentioning the ticket that were last updated before the change (stale docs).
"""

# The core query: chat-originated requirements that are still current, unimplemented and not dismissed, with evidence.
DRIFT = """
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
                         implements: old.text}) AS stale_prs,
       collect(DISTINCT {id: doc.id, title: doc.title, updated: doc.updated, url: doc.url}) AS stale_docs
ORDER BY changed_ms
"""

# Retro: per sprint, what was decided, what shipped, where they diverge
SPRINT_DECISIONS = """
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
"""

# Retro: PRs merged in the sprint, their tickets, how each link was resolved, and which requirement they implement
SPRINT_SHIPPED = """
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
"""

# Chronological messages, tickets, PRs and requirements attached to a feature
FEATURE_TIMELINE = """
MATCH (f:Feature {id: $feature})
MATCH (x)-[:ABOUT]->(f)
WHERE x:Message OR x:Ticket OR x:PullRequest OR x:Requirement
WITH x, coalesce(x.ts_ms, x.at_ms, x.merged_ms, x.created_ms) AS at
OPTIONAL MATCH (p:Person)-[:POSTED|AUTHORED]->(x)
RETURN labels(x)[0] AS type, x.id AS id, coalesce(x.text, x.title) AS text, at,
       coalesce(x.url, '') AS url, p.id AS person
ORDER BY at
"""

# How a feature's requirements evolved: each version, its source (ticket or chat), what it supersedes, which PRs implement it
DECISION_HISTORY = """
MATCH (f:Feature {id: $feature})<-[:ABOUT]-(t:Ticket)
MATCH (r:Requirement {ticket: t.id})
OPTIONAL MATCH (src)-[:STATES|CHANGES]->(r)
OPTIONAL MATCH (r)-[:SUPERSEDES]->(prev:Requirement)
OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(r)
RETURN t.id AS ticket, r.id AS requirement, r.text AS text, r.at AS at, r.origin AS origin,
       labels(src)[0] AS source_type, src.id AS source_id, coalesce(src.url, '') AS source_url,
       prev.id AS supersedes, collect(DISTINCT pr.number) AS implemented_by, r.at_ms AS at_ms
ORDER BY ticket, at_ms
"""

# Who knows a topic: people connected to the feature through anything they wrote,
# weighted by kind (a decision or PR counts more than a chat message).
WHO_KNOWS = """
MATCH (f:Feature {id: $feature})
MATCH (p:Person)-[rel:POSTED|AUTHORED|MADE]->(x)
WHERE (x)-[:ABOUT]->(f) OR (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f)
WITH p, x, CASE WHEN x:Decision THEN 5 WHEN x:PullRequest THEN 4 WHEN x:Ticket THEN 3 ELSE 1 END AS w
RETURN p.id AS person, p.name AS name, p.role AS role, sum(w) AS score, count(x) AS items
ORDER BY score DESC
"""

# Impact: everything reachable downstream of a decision (requirement -> ticket -> PRs, people)
DECISION_IMPACT = """
MATCH (d:Decision {id: $decision})-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(owner:Person)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (other:Ticket)-[:ABOUT]->(:Feature)<-[:ABOUT]-(t) WHERE other <> t
RETURN d.text AS decision, t.id AS ticket, owner.id AS owner,
       collect(DISTINCT pr.number) AS prs, collect(DISTINCT other.id) AS related_tickets
"""


# How are two things connected? Bounded undirected search over causal relationships
# (FalkorDB's shortestPath is directed-only). ABOUT is left out on purpose: going
# through the Feature hub is always short and explains nothing.
CONNECTION = """
MATCH (a {id: $a}), (b {id: $b})
MATCH p = (a)-[:POSTED|REPLY_TO|CHANGES|AMENDS|STATES|REFERENCES|IMPLEMENTS|MADE|AUTHORED|ASSIGNED_TO|SUPERSEDES|MENTIONS|RECORDED_IN*1..7]-(b)
RETURN [n IN nodes(p) | {id: n.id, type: labels(n)[0]}] AS nodes, [r IN relationships(p) | type(r)] AS rels,
       [r IN relationships(p) | startNode(r).id] AS starts, length(p) AS hops
ORDER BY hops LIMIT 1
"""

# Coverage: merged work that no ticket explains
ORPHAN_PRS = """
MATCH (a:Person)-[:AUTHORED]->(pr:PullRequest)
WHERE NOT (pr)-[:REFERENCES]->(:Ticket)
RETURN pr.number AS pr, pr.title AS title, pr.url AS url, a.id AS author, pr.merged AS merged ORDER BY pr
"""

# Coverage: tickets closed as Done with no PR referencing them
DONE_WITHOUT_PR = """
MATCH (t:Ticket) WHERE t.state = 'Done' AND NOT (:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person)
RETURN t.id AS ticket, t.title AS title, p.id AS owner ORDER BY ticket
"""

# Coverage: tickets no chat message ever mentions
UNDISCUSSED_TICKETS = """
MATCH (t:Ticket) WHERE NOT (:Message)-[:MENTIONS]->(t)
OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
RETURN t.id AS ticket, t.title AS title, t.state AS state, f.name AS feature ORDER BY ticket
"""

# Knowledge concentration ("bus factor"): share of a feature's weighted involvement held by its top person
KNOWLEDGE_RISK = """
MATCH (f:Feature)
MATCH (p:Person)-[:POSTED|AUTHORED|MADE]->(x)
WHERE (x)-[:ABOUT]->(f) OR (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f)
WITH f, p, sum(CASE WHEN x:Decision THEN 5 WHEN x:PullRequest THEN 4 WHEN x:Ticket THEN 3 ELSE 1 END) AS w
ORDER BY w DESC
WITH f, collect({person: p.id, name: p.name, w: w}) AS people, sum(w) AS total
RETURN f.id AS feature, f.name AS name, people[0].name AS top_person, people[0].w * 1.0 / total AS top_share,
       size(people) AS people, total
ORDER BY top_share DESC
"""

# Everything on a feature's time axis: requirement versions (ticket + chat) and PRs
FEATURE_EVENTS = """
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
"""

def rows(g, query: str, **params) -> list[dict]:
    res = g.query(query, params)
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


def drift(g, feature: str | None = None, ticket: str | None = None) -> list[dict]:
    out = rows(g, DRIFT, feature=feature, ticket=ticket)
    for d in out:  # OPTIONAL MATCH with no hit collects a map of nulls
        d["stale_docs"] = [x for x in d["stale_docs"] if x["id"] is not None]
    return out
