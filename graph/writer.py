"""Writes Events into FalkorDB. Every write is a MERGE on `id`, so re-ingesting is safe.

Times are stored twice: `*_ms` (epoch ms, used in Cypher comparisons) and the ISO string
(for display).
"""

from pipeline.events import Event, find_ticket_refs, to_ms


def apply_schema(g) -> None:
    # every MERGE/lookup is on id; the rest are the hot non-id lookups (verified with GRAPH.EXPLAIN,
    # see scripts/explain_queries.py): requirements of a ticket, messages by time, PRs by number
    for label, prop in [
        (lab, "id")
        for lab in (
            "Person",
            "Message",
            "Ticket",
            "PullRequest",
            "Document",
            "Feature",
            "Requirement",
            "Decision",
            "Sprint",
            "Task",
            "Chunk",
            "Team",
            "Project",
            "Client",
            "Deliverable",
        )
    ] + EXTRA_INDEXES:
        try:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:  # index already exists
            if "already indexed" not in str(e).lower():
                raise
    # Full-text indexes (RediSearch under the hood: stemming, prefix queries) power /api/search
    for label, props in FULLTEXT.items():
        try:
            g.query(f"CALL db.idx.fulltext.createNodeIndex('{label}', {', '.join(repr(p) for p in props)})")
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise


EXTRA_INDEXES = [("Requirement", "ticket"), ("Message", "ts_ms"), ("PullRequest", "number"), ("Ticket", "state")]

FULLTEXT = {
    "Message": ("text",),
    "Ticket": ("title", "description"),
    "PullRequest": ("title", "body"),
    "Person": ("name", "role"),
    "Document": ("title", "text"),
}


def write_people(g, people: list[dict]) -> None:
    g.query(
        "UNWIND $rows AS r MERGE (p:Person {id: r.id}) SET p.name = r.name, p.role = r.role, p.groups = coalesce(r.groups, []), p.email = r.email",
        {"rows": people},
    )


def write_sprints(g, sprints: list[dict]) -> None:
    rows = [{**s, "start_ms": to_ms(s["start"]), "end_ms": to_ms(s["end"])} for s in sprints]
    g.query(
        """UNWIND $rows AS r MERGE (s:Sprint {id: r.id})
           SET s.name = r.name, s.start = r.start, s.end = r.end, s.start_ms = r.start_ms, s.end_ms = r.end_ms""",
        {"rows": rows},
    )


def write_messages(g, events: list[Event]) -> None:
    rows = [
        {
            "id": e.id,
            "source": e.source,
            "channel": e.channel,
            "author": e.author,
            "ts": e.ts,
            "ts_ms": to_ms(e.ts),
            "text": e.text,
            "url": e.url,
            "thread_of": e.thread_of,
            "refs": find_ticket_refs(e.text),
        }
        for e in events
    ]
    _ensure_people(g, [r["author"] for r in rows])
    for chunk in _chunks(rows):
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


BATCH = 500  # rows per UNWIND: one round-trip per chunk instead of several per entity


def _chunks(rows: list[dict], n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def _ensure_people(g, ids) -> None:
    ids = sorted({i for i in ids if i})
    if ids:
        g.query("UNWIND $ids AS id MERGE (p:Person {id: id}) ON CREATE SET p.name = id", {"ids": ids})


def write_tickets(g, events: list[Event]) -> None:
    rows = []
    for e in events:
        x = e.extra
        versions = x.get("versions") or [{"at": e.ts, "to": x["description"], "actor": e.author}]
        rows.append(
            {
                "id": e.id,
                "title": x["title"],
                "description": x["description"],
                "state": x["state"],
                "priority": x.get("priority"),
                "labels": x.get("labels", []),
                "url": e.url,
                "created": e.ts,
                "created_ms": to_ms(e.ts),
                "updated": x["updated_at"],
                "updated_ms": to_ms(x["updated_at"]),
                "desc_updated_ms": to_ms(versions[-1]["at"]),
                "completed_ms": to_ms(x.get("completed_at")),
                "versions": [v["to"] for v in versions],
                "version_actors": [v.get("actor") or e.author for v in versions],
                "version_times": [to_ms(v["at"]) for v in versions],
                "author": e.author,
                "assignee": x.get("assignee"),
                "sprint": x.get("sprint"),
            }
        )
    _ensure_people(g, [r["author"] for r in rows] + [r["assignee"] for r in rows])
    for chunk in _chunks(rows):
        g.query(
            """UNWIND $rows AS r
               MERGE (t:Ticket {id: r.id})
               SET t.title = r.title, t.description = r.description, t.state = r.state, t.priority = r.priority,
                   t.labels = r.labels, t.url = r.url, t.created = r.created, t.created_ms = r.created_ms,
                   t.updated = r.updated, t.updated_ms = r.updated_ms, t.desc_updated_ms = r.desc_updated_ms,
                   t.completed_ms = r.completed_ms, t.versions = r.versions, t.version_times = r.version_times,
                   t.version_actors = r.version_actors
               WITH t, r
               MATCH (a:Person {id: r.author})
               MERGE (a)-[:AUTHORED]->(t)""",
            {"rows": chunk},
        )
        g.query(
            """UNWIND $rows AS r WITH r WHERE r.assignee IS NOT NULL
                   MATCH (t:Ticket {id: r.id}), (p:Person {id: r.assignee}) MERGE (t)-[:ASSIGNED_TO]->(p)""",
            {"rows": chunk},
        )
        g.query(
            """UNWIND $rows AS r WITH r WHERE r.sprint IS NOT NULL
                   MATCH (t:Ticket {id: r.id}), (s:Sprint {id: r.sprint}) MERGE (t)-[:IN_SPRINT]->(s)""",
            {"rows": chunk},
        )


def write_org(g, org: dict) -> None:
    """Org structure (data/scenario/org.json; in a real company: the tracker's projects, target dates and 'blocks'
    links, the HR system or GitHub teams, the CRM):
        Person -MEMBER_OF-> Team          Person -OWNS-> Project -INCLUDES-> Ticket -BLOCKS-> Ticket
        Deliverable -FOR-> Client         Deliverable -NEEDS-> Project       Person -OWNS-> Deliverable
        Message -CONCERNS-> Client        (a message that names the client)"""
    day = lambda d: to_ms(f"{d}T00:00:00Z")  # noqa: E731
    g.query(
        """UNWIND $rows AS r MERGE (t:Team {id: r.id}) SET t.name = r.name
           WITH t, r UNWIND r.members AS m MATCH (p:Person {id: m}) MERGE (p)-[:MEMBER_OF]->(t)""",
        {"rows": org.get("teams", [])},
    )
    projects = [{**p, "launch_ms": day(p["launch"])} for p in org.get("projects", [])]
    g.query(
        """UNWIND $rows AS r MERGE (p:Project {id: r.id})
           SET p.name = r.name, p.about = r.about, p.launch = r.launch, p.launch_ms = r.launch_ms
           WITH p, r UNWIND r.tickets AS tid MATCH (t:Ticket {id: tid}) MERGE (p)-[:INCLUDES]->(t)""",
        {"rows": projects},
    )
    g.query("UNWIND $rows AS r MATCH (p:Project {id: r.id}), (o:Person {id: r.owner}) MERGE (o)-[:OWNS]->(p)", {"rows": projects})
    g.query(
        "UNWIND $rows AS r MATCH (a:Ticket {id: r.from}), (b:Ticket {id: r.to}) MERGE (a)-[x:BLOCKS]->(b) SET x.why = r.why",
        {"rows": org.get("blocks", [])},
    )
    g.query("UNWIND $rows AS r MERGE (c:Client {id: r.id}) SET c.name = r.name, c.aliases = coalesce(r.aliases, [])", {"rows": org.get("clients", [])})
    dels = [{**d, "due_ms": day(d["due"])} for d in org.get("deliverables", [])]
    g.query(
        """UNWIND $rows AS r MERGE (d:Deliverable {id: r.id}) SET d.title = r.title, d.due = r.due, d.due_ms = r.due_ms
           WITH d, r MATCH (c:Client {id: r.client}) MERGE (d)-[:FOR]->(c)
           WITH d, r UNWIND r.needs AS pid MATCH (p:Project {id: pid}) MERGE (d)-[:NEEDS]->(p)""",
        {"rows": dels},
    )
    g.query("UNWIND $rows AS r MATCH (d:Deliverable {id: r.id}), (o:Person {id: r.owner}) MERGE (o)-[:OWNS]->(d)", {"rows": dels})
    names = [{"client": c["id"], "alias": a} for c in org.get("clients", []) for a in {c["name"], *c.get("aliases", [])}]
    g.query(
        """UNWIND $rows AS r MATCH (c:Client {id: r.client}) MATCH (m:Message) WHERE m.text CONTAINS r.alias
           MERGE (m)-[:CONCERNS]->(c)""",
        {"rows": names},
    )


def write_pull_requests(g, events: list[Event]) -> None:
    rows = [
        {
            "id": e.id,
            "number": e.extra["number"],
            "title": e.extra["title"],
            "body": e.extra["body"],
            "state": e.extra["state"],
            "url": e.url,
            "created": e.ts,
            "created_ms": to_ms(e.ts),
            "merged": e.extra.get("merged_at"),
            "merged_ms": to_ms(e.extra.get("merged_at")),
            "author": e.author,
            # Hard link: "Fixes BD-101", "(BD-107)", "BD-101: ..." in title or body
            "refs": find_ticket_refs(e.text),
        }
        for e in events
    ]
    _ensure_people(g, [r["author"] for r in rows])
    for chunk in _chunks(rows):
        g.query(
            """UNWIND $rows AS r
               MERGE (pr:PullRequest {id: r.id})
               SET pr.number = r.number, pr.title = r.title, pr.body = r.body, pr.state = r.state, pr.url = r.url,
                   pr.created = r.created, pr.created_ms = r.created_ms, pr.merged = r.merged, pr.merged_ms = r.merged_ms
               WITH pr, r
               MATCH (a:Person {id: r.author})
               MERGE (a)-[:AUTHORED]->(pr)""",
            {"rows": chunk},
        )
        g.query(
            """UNWIND $rows AS r UNWIND r.refs AS ref
                   MATCH (pr:PullRequest {id: r.id}), (t:Ticket {id: ref})
                   MERGE (pr)-[:REFERENCES]->(t)""",
            {"rows": chunk},
        )
        # Sprint membership by merge (or creation) date
        g.query(
            """UNWIND $rows AS r
                   MATCH (pr:PullRequest {id: r.id}), (s:Sprint)
                   WITH pr, s, coalesce(pr.merged_ms, pr.created_ms) AS at
                   WHERE at >= s.start_ms AND at <= s.end_ms
                   MERGE (pr)-[:IN_SPRINT]->(s)""",
            {"rows": chunk},
        )


def write_documents(g, events: list[Event]) -> None:
    """Docs (PRDs, design notes): Person -AUTHORED-> Document -MENTIONS-> Ticket."""
    rows = [
        {
            "id": e.id,
            "title": e.extra["title"],
            "text": e.text,
            "url": e.url,
            "created": e.ts,
            "created_ms": to_ms(e.ts),
            "updated": e.extra["updated"],
            "updated_ms": to_ms(e.extra["updated"]),
            "author": e.author,
            "refs": e.extra["tickets"],
            "declared": e.extra.get("declared") or [],
            # restricted docs always include their author (see pipeline/access.py)
            "acl": sorted(set(e.extra.get("acl") or []) | {f"person:{e.author}"}) if e.extra.get("acl") else None,
        }
        for e in events
    ]
    _ensure_people(g, [r["author"] for r in rows])
    for chunk in _chunks(rows):
        g.query(
            """UNWIND $rows AS r
               MERGE (d:Document {id: r.id})
               SET d.title = r.title, d.text = r.text, d.url = r.url, d.created = r.created, d.created_ms = r.created_ms,
                   d.updated = r.updated, d.updated_ms = r.updated_ms, d.acl = r.acl, d.declared = r.declared
               WITH d, r
               MATCH (a:Person {id: r.author})
               MERGE (a)-[:AUTHORED]->(d)""",
            {"rows": chunk},
        )
        g.query(
            """UNWIND $rows AS r UNWIND r.refs AS ref
                   MATCH (d:Document {id: r.id}), (t:Ticket {id: ref})
                   MERGE (d)-[:MENTIONS]->(t)""",
            {"rows": chunk},
        )
