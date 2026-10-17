"""Browsing the company brain: full-text search, person profiles, neighbourhood expansion."""

import re

from graph import queries as Q
from graph.writer import FULLTEXT

ID_LIKE = re.compile(r"^(BD-\d+|PR-\d+|#\d+)$", re.I)


def _fulltext_query(text: str) -> str | None:
    """User text -> safe RediSearch query: plain words, prefix match on the last one."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    words = [w for w in words if len(w) > 1]
    if not words:
        return None
    if len(words[-1]) >= 3:
        words[-1] += "*"
    return " ".join(words)


def search(g, text: str, limit: int = 12) -> list[dict]:
    text = text.strip()
    results: list[dict] = []
    if ID_LIKE.match(text):
        nid = text.upper().replace("#", "PR-")
        label = Q.label_of(g, nid)
        if label:
            results += Q.rows(
                g,
                f"""MATCH (n:{label} {{id: $id}}) RETURN n.id AS id, labels(n)[0] AS type,
                                    coalesce(n.title, n.name, n.text) AS label, 9.0 AS score""",
                id=nid,
            )
    low = text.lower()
    results += [
        {"id": p["id"], "type": "Person", "label": p["name"], "score": 9.0}
        for p in Q.rows(g, "MATCH (p:Person) RETURN p.id AS id, p.name AS name")
        if low and (low == p["id"] or low == (p["name"] or "").split(" ")[0].lower() or low == (p["name"] or "").lower())
    ]
    q = _fulltext_query(text)
    if q:
        for label in FULLTEXT:
            try:
                rows = Q.rows(
                    g,
                    f"""CALL db.idx.fulltext.queryNodes('{label}', $q) YIELD node, score
                                     RETURN node.id AS id, '{label}' AS type,
                                            coalesce(node.title, node.name, node.text) AS label, score
                                     ORDER BY score DESC LIMIT $limit""",
                    q=q,
                    limit=limit,
                )
            except Exception:  # noqa: BLE001 - index missing on an old graph
                rows = []
            results += rows
    seen, out = set(), []
    weight = {"Person": 2.0, "Ticket": 2.0, "PullRequest": 1.8, "Document": 1.8, "Message": 1.0}  # structure before chatter
    for r in sorted(results, key=lambda r: -(r["score"] * weight.get(r["type"], 1.0))):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    feats = {}
    for label in {r["type"] for r in out[:limit]}:  # one indexed lookup per label present in the hits
        if label not in Q.LABELS:
            continue
        feats.update(
            {
                r["id"]: r["feature"]
                for r in Q.rows(
                    g,
                    f"""
            UNWIND $ids AS i MATCH (n:{label} {{id: i}})
            OPTIONAL MATCH (n)-[:ABOUT]->(f:Feature)
            OPTIONAL MATCH (n)-[:REFERENCES|MENTIONS]->(:Ticket)-[:ABOUT]->(f2:Feature)
            RETURN i AS id, coalesce(f.id, f2.id) AS feature""",
                    ids=[r["id"] for r in out[:limit] if r["type"] == label],
                )
            }
        )
    for r in out[:limit]:
        r["feature"] = feats.get(r["id"])
    return out[:limit]


def person(g, pid: str) -> dict | None:
    p = Q.rows(g, "MATCH (p:Person {id: $id}) RETURN p.id AS id, p.name AS name, p.role AS role", id=pid)
    if not p:
        return None
    out = p[0]
    out["owns"] = Q.rows(
        g,
        # owner = creator or assignee, the same rule as decision rights (pipeline.resolve.has_decision_rights)
        """MATCH (p:Person {id: $id}) MATCH (t:Ticket) WHERE (p)-[:AUTHORED]->(t) OR (t)-[:ASSIGNED_TO]->(p)
                               OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
                               OPTIONAL MATCH (t)-[a:ASSIGNED_TO]->(p)
                               OPTIONAL MATCH (p)-[c:AUTHORED]->(t)
                               RETURN t.id AS ticket, t.title AS title, t.state AS state, f.name AS feature,
                                      CASE WHEN a IS NOT NULL AND c IS NOT NULL THEN 'created, assigned'
                                           WHEN a IS NOT NULL THEN 'assigned' ELSE 'created' END AS role
                               ORDER BY ticket""",
        id=pid,
    )
    out["prs"] = Q.rows(
        g,
        """MATCH (:Person {id: $id})-[:AUTHORED]->(pr:PullRequest)
                              OPTIONAL MATCH (pr)-[:REFERENCES]->(t:Ticket)
                              RETURN pr.number AS pr, pr.title AS title, pr.url AS url, collect(t.id) AS tickets,
                                     pr.number AS n ORDER BY n""",
        id=pid,
    )
    out["decisions"] = Q.rows(
        g,
        """MATCH (:Person {id: $id})-[:MADE]->(d:Decision)
                                    OPTIONAL MATCH (d)-[:CHANGES|DISMISSES]->(r:Requirement)
                                    RETURN d.id AS id, d.text AS text, d.at AS at, coalesce(d.kind, 'decision') AS kind,
                                           r.ticket AS ticket, d.at_ms AS t ORDER BY t""",
        id=pid,
    )
    out["features"] = Q.rows(
        g,
        """MATCH (:Person {id: $id})-[:POSTED|AUTHORED|MADE]->(x)
                                   WHERE (x)-[:ABOUT]->(:Feature) OR (x)-[:CHANGES]->(:Requirement)
                                   OPTIONAL MATCH (x)-[:ABOUT]->(f1:Feature)
                                   OPTIONAL MATCH (x)-[:CHANGES]->(:Requirement)-[:ABOUT]->(f2:Feature)
                                   WITH coalesce(f1, f2) AS f, x WHERE f IS NOT NULL
                                   RETURN f.id AS id, f.name AS name,
                                          sum(CASE WHEN x:Decision THEN 5 WHEN x:PullRequest THEN 4 WHEN x:Ticket THEN 3 ELSE 1 END) AS score
                                   ORDER BY score DESC""",
        id=pid,
    )
    out["docs"] = Q.rows(
        g,
        """MATCH (:Person {id: $id})-[:AUTHORED]->(d:Document)
                               OPTIONAL MATCH (d)-[:MENTIONS]->(t:Ticket)
                               RETURN d.id AS id, d.title AS title, d.updated AS updated, collect(t.id) AS tickets
                               ORDER BY id""",
        id=pid,
    )
    out["messages"] = Q.rows(g, "MATCH (:Person {id: $id})-[:POSTED]->(m:Message) RETURN count(m) AS n", id=pid)[0]["n"]
    out["drift_caused"] = [d for d in Q.drift(g) if d["changed_by"] == pid]
    out["stale_work"] = [
        d
        for d in Q.drift(g)
        if any(r["owner"] == pid for r in Q.rows(g, "MATCH (:Ticket {id: $t})-[:ASSIGNED_TO]->(p:Person) RETURN p.id AS owner", t=d["ticket"]))
    ]
    return out


def neighbors(g, nid: str, limit: int = 40) -> dict:
    label = Q.label_of(g, nid)
    if not label:
        return {"nodes": [], "edges": []}
    rows = Q.rows(
        g,
        f"""MATCH (n:{label} {{id: $id}})-[r]-(m)
                        WHERE NOT m:Sprint AND NOT m:Build
                        RETURN m.id AS id, labels(m)[0] AS type, coalesce(m.title, m.name, m.text, m.id) AS label,
                               coalesce(m.text, m.description, m.title) AS text, m.number AS number,
                               type(r) AS rel, startNode(r).id AS src
                        LIMIT $limit""",
        id=nid,
        limit=limit,
    )
    nodes, edges = {}, []
    for r in rows:
        label = f"PR #{r['number']}" if r["type"] == "PullRequest" else (r["id"] if r["type"] == "Ticket" else (r["label"] or r["id"])[:60])
        nodes[r["id"]] = {"id": r["id"], "type": r["type"], "label": label, "text": r["text"]}
        a, b = (nid, r["id"]) if r["src"] == nid else (r["id"], nid)
        edges.append({"from": a, "rel": r["rel"], "to": b})
    return {"nodes": list(nodes.values()), "edges": edges}
