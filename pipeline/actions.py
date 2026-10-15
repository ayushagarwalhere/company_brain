"""Actions that close the loop on drift. Both are recorded in the graph, so they stay auditable.

  write_to_ticket  the decided requirement becomes the ticket's next description version:
                   (Ticket)-[:STATES]->(new version)-[:SUPERSEDES]->(chat requirement)
  dismiss          someone decides to keep the old scope:
                   (Person)-[:MADE]->(Decision {kind: 'dismissal'})-[:DISMISSES]->(chat requirement)
"""
from datetime import datetime, timezone

from graph import queries as Q
from pipeline.events import to_ms


def _now() -> tuple[str, int]:
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso, to_ms(iso)


def _open_drift(g, requirement: str) -> dict:
    found = [d for d in Q.drift(g) if d["requirement"] == requirement]
    if not found:
        raise ValueError(f"{requirement} is not an open drift")
    return found[0]


def write_to_ticket(g, requirement: str, actor: str = "maya") -> dict:
    d = _open_drift(g, requirement)
    ticket = d["ticket"]
    t = Q.rows(g, "MATCH (t:Ticket {id: $t}) RETURN t.versions AS v, t.version_times AS vt", t=ticket)[0]
    versions, times = list(t["v"] or []), list(t["vt"] or [])
    iso, ms = _now()
    new_id = f"req:{ticket}:v{len(versions) + 1}"
    text = d["requirement_text"]
    g.query("""MATCH (t:Ticket {id: $t}), (chat:Requirement {id: $chat})
               OPTIONAL MATCH (chat)-[:ABOUT]->(f:Feature)
               MERGE (q:Requirement {id: $id})
               SET q.text = $text, q.at_ms = $ms, q.at = $iso, q.origin = 'ticket', q.ticket = $t, q.written_by = $actor
               MERGE (t)-[:STATES {at_ms: $ms}]->(q)
               MERGE (q)-[:SUPERSEDES]->(chat)
               SET t.description = $text, t.desc_updated_ms = $ms, t.updated = $iso, t.updated_ms = $ms,
                   t.versions = $versions, t.version_times = $times
               WITH q, f WHERE f IS NOT NULL
               MERGE (q)-[:ABOUT]->(f)""",
            {"t": ticket, "chat": requirement, "id": new_id, "text": text, "ms": ms, "iso": iso, "actor": actor,
             "versions": versions + [text], "times": times + [ms]})
    g.query("MATCH (a:Alert)-[:FLAGS]->(:Requirement {id: $r}) SET a.status = 'resolved'", {"r": requirement})
    return {"status": "written", "ticket": ticket, "version": new_id, "text": text}


def dismiss(g, requirement: str, actor: str = "maya", reason: str = "keep the old scope") -> dict:
    _open_drift(g, requirement)
    iso, ms = _now()
    did = f"dismiss:{requirement}"
    g.query("""MATCH (r:Requirement {id: $r}), (p:Person {id: $actor})
               MERGE (d:Decision {id: $did})
               SET d.kind = 'dismissal', d.text = $reason, d.at = $iso, d.at_ms = $ms
               MERGE (p)-[:MADE]->(d)
               MERGE (d)-[:DISMISSES]->(r)""",
            {"r": requirement, "actor": actor, "did": did, "reason": reason, "iso": iso, "ms": ms})
    g.query("MATCH (a:Alert)-[:FLAGS]->(:Requirement {id: $r}) SET a.status = 'dismissed'", {"r": requirement})
    return {"status": "dismissed", "requirement": requirement, "by": actor}
