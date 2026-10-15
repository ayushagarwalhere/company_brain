"""Writes Events into FalkorDB. Every write is a MERGE on `id`, so re-ingesting is safe.

Times are stored twice: `*_ms` (epoch ms, used in Cypher comparisons) and the ISO string
(for display).
"""
from pipeline.events import Event, find_ticket_refs, to_ms


def apply_schema(g) -> None:
    for label in ("Person", "Message", "Ticket", "PullRequest", "Feature", "Requirement", "Decision", "Sprint"):
        try:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
        except Exception as e:  # index already exists
            if "already indexed" not in str(e).lower():
                raise


def write_people(g, people: list[dict]) -> None:
    g.query(
        "UNWIND $rows AS r MERGE (p:Person {id: r.id}) SET p.name = r.name, p.role = r.role",
        {"rows": people},
    )


def write_sprints(g, sprints: list[dict]) -> None:
    rows = [{**s, "start_ms": to_ms(s["start"]), "end_ms": to_ms(s["end"])} for s in sprints]
    g.query(
        """UNWIND $rows AS r MERGE (s:Sprint {id: r.id})
           SET s.name = r.name, s.start = r.start, s.end = r.end, s.start_ms = r.start_ms, s.end_ms = r.end_ms""",
        {"rows": rows},
    )


def _ensure_person(g, pid: str) -> None:
    g.query("MERGE (p:Person {id: $id}) ON CREATE SET p.name = $id", {"id": pid})


def write_messages(g, events: list[Event]) -> None:
    rows = [{
        "id": e.id, "source": e.source, "channel": e.channel, "author": e.author, "ts": e.ts,
        "ts_ms": to_ms(e.ts), "text": e.text, "url": e.url, "thread_of": e.thread_of,
        "refs": find_ticket_refs(e.text),
    } for e in events]
    for pid in {r["author"] for r in rows}:
        _ensure_person(g, pid)
    for i in range(0, len(rows), 200):
        chunk = rows[i:i + 200]
        g.query(
            """UNWIND $rows AS r
               MERGE (m:Message {id: r.id})
               SET m.source = r.source, m.channel = r.channel, m.ts = r.ts, m.ts_ms = r.ts_ms,
                   m.text = r.text, m.url = r.url
               WITH m, r
               MATCH (p:Person {id: r.author})
               MERGE (p)-[:POSTED]->(m)""",
            {"rows": chunk},
        )
        # Replies (parent may arrive later in the same batch, so this runs after the MERGE above)
        g.query(
            """UNWIND $rows AS r WITH r WHERE r.thread_of IS NOT NULL
               MATCH (m:Message {id: r.id}), (parent:Message {id: r.thread_of})
               MERGE (m)-[:REPLY_TO]->(parent)""",
            {"rows": chunk},
        )
    link_mentions(g, rows)


def link_mentions(g, rows: list[dict]) -> None:
    """Resolution signal 1 (hard links): a message that names a ticket id MENTIONS it."""
    pairs = [{"m": r["id"], "t": t} for r in rows for t in r["refs"]]
    g.query(
        """UNWIND $pairs AS p
           MATCH (m:Message {id: p.m}), (t:Ticket {id: p.t})
           MERGE (m)-[:MENTIONS]->(t)""",
        {"pairs": pairs},
    )


def write_tickets(g, events: list[Event]) -> None:
    for e in events:
        x = e.extra
        versions = x.get("versions") or [{"at": e.ts, "to": x["description"], "actor": e.author}]
        for pid in {e.author, x.get("assignee")} - {None}:
            _ensure_person(g, pid)
        g.query(
            """MERGE (t:Ticket {id: $id})
               SET t.title = $title, t.description = $description, t.state = $state, t.priority = $priority,
                   t.labels = $labels, t.url = $url, t.created = $created, t.created_ms = $created_ms,
                   t.updated = $updated, t.updated_ms = $updated_ms,
                   t.desc_updated_ms = $desc_updated_ms, t.completed_ms = $completed_ms,
                   t.versions = $versions, t.version_times = $version_times
               WITH t
               MATCH (a:Person {id: $author})
               MERGE (a)-[:AUTHORED]->(t)""",
            {
                "id": e.id, "title": x["title"], "description": x["description"], "state": x["state"],
                "priority": x.get("priority"), "labels": x.get("labels", []), "url": e.url,
                "created": e.ts, "created_ms": to_ms(e.ts),
                "updated": x["updated_at"], "updated_ms": to_ms(x["updated_at"]),
                "desc_updated_ms": to_ms(versions[-1]["at"]), "completed_ms": to_ms(x.get("completed_at")),
                "versions": [v["to"] for v in versions], "version_times": [to_ms(v["at"]) for v in versions],
                "author": e.author,
            },
        )
        if x.get("assignee"):
            g.query("MATCH (t:Ticket {id: $t}), (p:Person {id: $p}) MERGE (t)-[:ASSIGNED_TO]->(p)",
                    {"t": e.id, "p": x["assignee"]})
        if x.get("sprint"):
            g.query("MATCH (t:Ticket {id: $t}), (s:Sprint {id: $s}) MERGE (t)-[:IN_SPRINT]->(s)",
                    {"t": e.id, "s": x["sprint"]})


def write_pull_requests(g, events: list[Event]) -> None:
    for e in events:
        x = e.extra
        _ensure_person(g, e.author)
        g.query(
            """MERGE (pr:PullRequest {id: $id})
               SET pr.number = $number, pr.title = $title, pr.body = $body, pr.state = $state, pr.url = $url,
                   pr.created = $created, pr.created_ms = $created_ms,
                   pr.merged = $merged, pr.merged_ms = $merged_ms
               WITH pr
               MATCH (a:Person {id: $author})
               MERGE (a)-[:AUTHORED]->(pr)""",
            {
                "id": e.id, "number": x["number"], "title": x["title"], "body": x["body"], "state": x["state"],
                "url": e.url, "created": e.ts, "created_ms": to_ms(e.ts),
                "merged": x.get("merged_at"), "merged_ms": to_ms(x.get("merged_at")), "author": e.author,
            },
        )
        # Hard link: "Fixes BD-101", "(BD-107)", "BD-101: ..." in title or body
        g.query(
            """UNWIND $refs AS ref
               MATCH (pr:PullRequest {id: $id}), (t:Ticket {id: ref})
               MERGE (pr)-[:REFERENCES]->(t)""",
            {"id": e.id, "refs": find_ticket_refs(e.text)},
        )
        # Sprint membership by merge (or creation) date
        g.query(
            """MATCH (pr:PullRequest {id: $id}), (s:Sprint)
               WITH pr, s, coalesce(pr.merged_ms, pr.created_ms) AS at
               WHERE at >= s.start_ms AND at <= s.end_ms
               MERGE (pr)-[:IN_SPRINT]->(s)""",
            {"id": e.id},
        )
