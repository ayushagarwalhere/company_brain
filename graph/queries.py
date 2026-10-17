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

# One source for the involvement weights (config.INVOLVEMENT_WEIGHTS), used by WHO_KNOWS and KNOWLEDGE_RISK.
from config import INVOLVEMENT_DEFAULT_WEIGHT, INVOLVEMENT_WEIGHTS

WEIGHT_EXPR = "CASE " + " ".join(f"WHEN x:{label} THEN {w}" for label, w in INVOLVEMENT_WEIGHTS.items()) + f" ELSE {INVOLVEMENT_DEFAULT_WEIGHT} END"

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
                         merged_after: coalesce(pr.merged_ms, pr.created_ms) > r.at_ms,
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
WITH p, x, __W__ AS w
RETURN p.id AS person, p.name AS name, p.role AS role, sum(w) AS score, count(x) AS items
ORDER BY score DESC
""".replace("__W__", WEIGHT_EXPR)

# Impact: everything reachable downstream of a decision (requirement -> ticket -> PRs, people)
DECISION_IMPACT = """
MATCH (d:Decision {id: $decision})-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(owner:Person)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (other:Ticket)-[:ABOUT]->(:Feature)<-[:ABOUT]-(t) WHERE other <> t
RETURN d.text AS decision, t.id AS ticket, owner.id AS owner,
       collect(DISTINCT pr.number) AS prs, collect(DISTINCT other.id) AS related_tickets
"""


# How are two things connected? FalkorDB's algo.SPpaths finds the shortest path with
# relDirection 'both' (Cypher shortestPath is directed-only in FalkorDB). An earlier version
# enumerated every undirected path up to 7 hops and sorted them, which timed out at ~24k messages
# (benchmark/scale.py); SPpaths answers the same question in milliseconds. ABOUT is left out on
# purpose: going through the Feature hub is always short and explains nothing.
# __LA__ / __LB__ are replaced by labels from label_of() (whitelisted), so both endpoints come from an index seek.
CONNECTION = """
MATCH (a:__LA__ {id: $a}), (b:__LB__ {id: $b})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: 7, pathCount: 1,
                   relTypes: ['POSTED', 'REPLY_TO', 'CHANGES', 'AMENDS', 'STATES', 'REFERENCES', 'IMPLEMENTS', 'MADE',
                              'AUTHORED', 'ASSIGNED_TO', 'SUPERSEDES', 'MENTIONS', 'RECORDED_IN']})
YIELD path
RETURN [n IN nodes(path) | {id: n.id, type: labels(n)[0]}] AS nodes, [r IN relationships(path) | type(r)] AS rels,
       [r IN relationships(path) | startNode(r).id] AS starts, length(path) AS hops
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

# Unverified changes: a chat message that reads as a requirement change, from someone who doesn't own the ticket it was
# matched to, where that ticket was only a text-similarity guess. Kept visible instead of dropped; never counted as drift.
UNVERIFIED_CHANGES = """
MATCH (p:Person)-[:POSTED]->(m:Message)-[:SUGGESTS]->(q:Requirement {status: 'candidate'})-[:MAY_AMEND]->(t:Ticket)
RETURN q.id AS id, q.text AS text, q.at AS at, m.id AS message, m.source AS source, m.channel AS channel,
       p.id AS author, t.id AS ticket, t.title AS ticket_title ORDER BY q.at_ms DESC
"""

# Knowledge concentration ("bus factor"): share of a feature's weighted involvement held by its top person
KNOWLEDGE_RISK = """
MATCH (f:Feature)
MATCH (p:Person)-[:POSTED|AUTHORED|MADE]->(x)
WHERE (x)-[:ABOUT]->(f) OR (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f)
WITH f, p, sum(__W__) AS w
ORDER BY w DESC
WITH f, collect({person: p.id, name: p.name, w: w}) AS people, sum(w) AS total
RETURN f.id AS feature, f.name AS name, people[0].name AS top_person, people[0].w * 1.0 / total AS top_share,
       size(people) AS people, total
ORDER BY top_share DESC
""".replace("__W__", WEIGHT_EXPR)

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
    return [dict(zip(cols, r, strict=False)) for r in res.result_set]


# Same query anchored on one ticket: starts from the Requirement(ticket) index instead of a label scan
DRIFT_FOR_TICKET = DRIFT.replace(
    "MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)",
    "MATCH (r:Requirement {ticket: $ticket})\nMATCH (m:Message)-[:CHANGES]->(r)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)",
    1,
)
assert DRIFT_FOR_TICKET != DRIFT, "DRIFT's first MATCH changed; update DRIFT_FOR_TICKET"

LABELS = ("Person", "Ticket", "PullRequest", "Message", "Document", "Requirement", "Decision", "Feature", "Sprint")


def label_of(g, node_id: str) -> str | None:
    """Label of the node with this id, found through the per-label id indexes (never an all-node scan)."""
    for label in LABELS:
        if g.query(f"MATCH (n:{label} {{id: $id}}) RETURN 1 LIMIT 1", {"id": node_id}).result_set:
            return label
    return None


def connection(g, a: str, b: str) -> list[dict]:
    la, lb = label_of(g, a), label_of(g, b)
    if not la or not lb:
        return []
    return rows(g, CONNECTION.replace("__LA__", la).replace("__LB__", lb), a=a, b=b)


# One rule for every PR on a drifted ticket, used by the API, dashboard, agents, alerts and retro:
#   merged BEFORE the decision                          -> "old"        shipped the old version (stale)
#   merged AFTER it and IMPLEMENTS an older requirement -> "old_after"  shipped the old version after the decision (stale)
#   merged AFTER it with no IMPLEMENTS link either way  -> "unmatched"  may implement the new scope (NOT stale)
# (A PR that implements the decision itself would mean there is no drift.)
PR_STATUS_LABEL = {
    "old": "shipped the old version",
    "old_after": "shipped the old version after the decision",
    "unmatched": "unmatched, may implement the new scope",
}


def classify_prs(collected: list[dict]) -> tuple[list[dict], list[dict]]:
    """Groups the DRIFT query's per-(PR, implemented requirement) rows by PR and applies the rule above.
    Returns (stale PRs, unmatched PRs); each PR gets `status`, `label` and the older requirement it implements."""
    by_pr: dict = {}
    for x in collected:
        if x.get("pr") is None:
            continue
        p = by_pr.setdefault(x["pr"], {**x, "implements": None})
        p["implements"] = p["implements"] or x.get("implements")
    stale: list[dict] = []
    unmatched: list[dict] = []
    for p in by_pr.values():
        status = "unmatched" if p.get("merged_after") and not p["implements"] else "old_after" if p.get("merged_after") else "old"
        p.update(status=status, label=PR_STATUS_LABEL[status])
        (unmatched if status == "unmatched" else stale).append(p)
    return stale, unmatched


def drift(g, feature: str | None = None, ticket: str | None = None) -> list[dict]:
    out = rows(g, DRIFT_FOR_TICKET if ticket else DRIFT, feature=feature, ticket=ticket)
    for d in out:  # OPTIONAL MATCH with no hit collects a map of nulls
        d["stale_docs"] = [x for x in d["stale_docs"] if x["id"] is not None]
        d["stale_prs"], d["unmatched_prs"] = classify_prs(d["stale_prs"])
    return out
