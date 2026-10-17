"""The agent that gets work done: turns an open drift into concrete work, assigned by the graph, and does it.

plan(requirement)              what has to change and who owns each part, read from the graph:
                                 the ticket (its creator and assignee decide), every PR that shipped the old version
                                 (its author), every doc that still describes it (its author), and who else should know
apply(requirement, actor)      only someone with decision rights on the ticket: writes the decision into the ticket and
                                 opens a follow-up Task per stale PR and doc, assigned to that person
keep_old_scope(requirement, actor)   the same rights check, then a recorded dismissal
tasks(person) / complete(task, actor)   the follow-ups, and closing one (its assignee or a ticket owner)

Graph shape of a follow-up (kept across rebuilds by pipeline.human, like dismissals and write-backs):
  (Person approver)-[:APPROVED]->(Task {origin: 'human'})-[:ASSIGNED_TO]->(Person)
  (Task)-[:FIXES]->(PullRequest | Document),  (Task)-[:FOR]->(Requirement: the chat decision)
"""

from datetime import UTC, datetime

from graph import queries as Q
from pipeline.events import to_ms


class NotAllowed(Exception):
    """The actor has no decision rights on the ticket. The message names who does."""


def _now() -> tuple[str, int]:
    iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = to_ms(iso)
    assert ms is not None
    return iso, ms


def open_drift(g, requirement: str) -> dict:
    found = [d for d in Q.drift(g) if d["requirement"] == requirement]
    if not found:
        raise ValueError(f"{requirement} is not an open drift")
    return found[0]


def owners(g, ticket: str) -> dict:
    """Who may change this ticket's requirement: its creator and its assignee (the same rule as chat decisions)."""
    rows = Q.rows(
        g,
        """MATCH (t:Ticket {id: $t}) OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person)
           RETURN c.id AS creator, c.name AS creator_name, a.id AS assignee, a.name AS assignee_name""",
        t=ticket,
    )
    return rows[0] if rows else {}


def _who(o: dict) -> str:
    names = [
        f"{o.get('creator_name') or o.get('creator')} (created it)" if o.get("creator") else None,
        f"{o.get('assignee_name') or o.get('assignee')} (assigned)" if o.get("assignee") else None,
    ]
    return " or ".join(n for n in names if n) or "nobody on record"


def plan(g, requirement: str) -> dict:
    d = open_drift(g, requirement)
    own = owners(g, d["ticket"])
    items = [
        {
            "kind": "ticket",
            "target": d["ticket"],
            "assignee": own.get("assignee") or own.get("creator"),
            "what": f"Write the decision into {d['ticket']} (done by me when an owner approves)",
            "why": f"it still says: \"{d['ticket_text']}\"",
        }
    ]
    for p in d["stale_prs"]:
        a = Q.rows(g, "MATCH (p:Person)-[:AUTHORED]->(:PullRequest {number: $n}) RETURN p.id AS id", n=p["pr"])
        items.append(
            {
                "kind": "pr",
                "target": f"PR-{p['pr']}",
                "assignee": a[0]["id"] if a else None,
                "what": f"Change PR #{p['pr']} \"{p['title']}\" to the new requirement",
                "why": f"it {p['label']}",
            }
        )
    for doc in d["stale_docs"]:
        a = Q.rows(g, "MATCH (p:Person)-[:AUTHORED]->(:Document {id: $d}) RETURN p.id AS id", d=doc["id"])
        items.append(
            {
                "kind": "doc",
                "target": doc["id"],
                "assignee": a[0]["id"] if a else None,
                "what": f"Update {doc['id']} \"{doc['title']}\"",
                "why": "it still describes the old version",
            }
        )
    busy = {i["assignee"] for i in items} | {d["changed_by"]}
    tell = [r["person"] for r in Q.rows(g, Q.WHO_KNOWS, feature=d["feature"]) if r["person"] not in busy][:3]
    return {
        "drift": d,
        "owners": own,
        "decided_by": d["changed_by"],
        "items": items,
        "tell": tell,
        "can_apply": [x for x in (own.get("creator"), own.get("assignee")) if x],
    }


def format_plan(p: dict) -> str:
    d = p["drift"]
    lines = [f"*Plan for {d['ticket']} ({d['feature_name']})*: {d['changed_by']} decided \"{d['requirement_text']}\" on {d['changed_at'][:10]}."]
    for n, i in enumerate(p["items"], 1):
        who = "" if i["kind"] == "ticket" else f" → *{i['assignee'] or 'unassigned'}*"
        lines.append(f"{n}. {i['what']}{who} ({i['why']})")
    if p["tell"]:
        lines.append("Also tell: " + ", ".join(p["tell"]) + " (most involved in this feature).")
    lines.append(f"Who can approve: {_who(p['owners'])}. Reply `fix it` to apply, or `keep the old scope`.")
    return "\n".join(lines)


def _check(g, requirement: str, actor: str) -> dict:
    d = open_drift(g, requirement)
    own = owners(g, d["ticket"])
    if actor not in (own.get("creator"), own.get("assignee")):
        raise NotAllowed(f"Only {d['ticket']}'s owners can decide this: {_who(own)}. {actor} can't.")
    return d


def apply(g, requirement: str, actor: str) -> dict:
    """Owner approves: the ticket gets the decision, and each stale PR and doc gets an assigned follow-up."""
    from pipeline.actions import write_to_ticket

    _check(g, requirement, actor)
    p = plan(g, requirement)
    written = write_to_ticket(g, requirement, actor)
    iso, ms = _now()
    made = []
    for i in p["items"]:
        if i["kind"] == "ticket":
            continue
        tid = f"task:{requirement}:{i['target']}"
        num = g.query("MATCH (t:Task) RETURN coalesce(max(t.num), 0) + 1").result_set[0][0]
        g.query(
            """MERGE (t:Task {id: $id})
               ON CREATE SET t.num = $num, t.created = $iso, t.created_ms = $ms
               SET t.origin = 'human', t.kind = $kind, t.title = $what, t.why = $why, t.status = 'open',
                   t.target = $target, t.requirement = $req, t.assignee = $who, t.approved_by = $actor""",
            {
                "id": tid,
                "num": num,
                "iso": iso,
                "ms": ms,
                "kind": i["kind"],
                "what": i["what"],
                "why": i["why"],
                "target": i["target"],
                "req": requirement,
                "who": i["assignee"],
                "actor": actor,
            },
        )
        made.append(tid)
    relink_tasks(g)
    return {"status": "applied", "ticket": written["ticket"], "version": written["version"], "tasks": tasks(g, ids=made), "tell": p["tell"], "by": actor}


def keep_old_scope(g, requirement: str, actor: str, reason: str = "keep the old scope") -> dict:
    from pipeline.actions import dismiss

    _check(g, requirement, actor)
    return dismiss(g, requirement, actor, reason)


def relink_tasks(g) -> int:
    """(Re)attach every Task to its assignee, approver, the PR/doc it fixes and the decision it serves, by stable id.
    resolve() recreates Requirement nodes, so the FOR edge has to be re-made after every rebuild."""
    g.query("MATCH (t:Task) MATCH (p:Person {id: t.assignee}) MERGE (t)-[:ASSIGNED_TO]->(p)")
    g.query("MATCH (t:Task) MATCH (p:Person {id: t.approved_by}) MERGE (p)-[:APPROVED]->(t)")
    g.query("MATCH (t:Task {kind: 'pr'}) MATCH (x:PullRequest {id: t.target}) MERGE (t)-[:FIXES]->(x)")
    g.query("MATCH (t:Task {kind: 'doc'}) MATCH (x:Document {id: t.target}) MERGE (t)-[:FIXES]->(x)")
    return g.query("MATCH (t:Task) MATCH (r:Requirement {id: t.requirement}) MERGE (t)-[:FOR]->(r) RETURN count(t)").result_set[0][0]


def tasks(g, person: str | None = None, status: str | None = "open", ids: list[str] | None = None) -> list[dict]:
    return Q.rows(
        g,
        """MATCH (t:Task)
           WHERE ($person IS NULL OR t.assignee = $person) AND ($status IS NULL OR t.status = $status) AND ($ids IS NULL OR t.id IN $ids)
           RETURN t.id AS id, t.num AS num, t.kind AS kind, t.title AS title, t.why AS why, t.status AS status,
                  t.assignee AS assignee, t.approved_by AS approved_by, t.target AS target, t.created AS created
           ORDER BY t.num""",
        person=person,
        status=status,
        ids=ids,
    )


def complete(g, num: int, actor: str) -> dict:
    """Close follow-up T-<num>. Its assignee or the person who approved it may close it."""
    t = Q.rows(g, "MATCH (t:Task {num: $n}) RETURN t.id AS id, t.assignee AS assignee, t.approved_by AS approver, t.status AS status", n=num)
    if not t:
        raise ValueError(f"no task T-{num}")
    if actor not in (t[0]["assignee"], t[0]["approver"]):
        raise NotAllowed(f"T-{num} is {t[0]['assignee']}'s (approved by {t[0]['approver']}); {actor} can't close it.")
    iso, _ = _now()
    g.query("MATCH (t:Task {num: $n}) SET t.status = 'done', t.done_by = $a, t.done = $iso", {"n": num, "a": actor, "iso": iso})
    return {"status": "done", "task": f"T-{num}", "by": actor}


def format_tasks(rows: list[dict]) -> str:
    if not rows:
        return "No open follow-ups."
    return "\n".join(f"• *T-{r['num']}* {r['title']} → {r['assignee'] or 'unassigned'} ({r['why']}; approved by {r['approved_by']})" for r in rows)
