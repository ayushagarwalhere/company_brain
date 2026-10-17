"""Org-level changes that arrive as chat or tracker events, applied to the graph as they happen.

Project status from chat ("We are cancelling Project Gamma, effective immediately"):
    Message -CHANGES_STATUS {to, at}-> Project     and Project.status / status_by / status_at / status_msg
Only someone who may decide it can change a project: its owner, a lead (access group "leads"), or the owner's
manager (HR). Anyone else's message is kept as a message, and the project is left as it was.
Status words are matched in the same sentence as the project's name, so "the Gamma retro is cancelled" is not a
project cancellation unless it names "Project Gamma" with a status word about it.

New tickets from the tracker (a Jira/Linear "issue created" webhook): the ticket, who opened it, who it's assigned
to, and the project that includes it.
"""

import re

from graph import queries as Q
from pipeline.events import Event, to_ms

STATUS_WORDS: list[tuple[str, str]] = [
    (r"\b(cancel+(?:ing|ed|s)?|scrap(?:ping|ped|s)?|kill(?:ing|ed|s)?|shut(?:ting)? down|sunset(?:ting)?|stop(?:ping)? work on)\b", "cancelled"),
    (r"\b(paus(?:e|es|ing|ed)|on hold|freez(?:e|es|ing)|frozen)\b", "on hold"),
    (r"\b(resum(?:e|es|ing|ed)|restart(?:s|ing|ed)?|un-?paus(?:e|ing|ed)|back on|reviv(?:e|ing|ed))\b", "active"),
]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def find_status_change(g, text: str) -> tuple[dict, str] | None:
    """(project, new status) when the text says a named project is cancelled, paused or resumed."""
    projects = Q.rows(g, "MATCH (p:Project) RETURN p.id AS id, p.name AS name, coalesce(p.status, 'active') AS status")
    for sentence in _sentences(text):
        low = sentence.lower()
        for p in projects:
            names = {(p["name"] or "").lower(), f"project {p['id'].lower()}"}
            if not any(n and re.search(rf"\b{re.escape(n)}\b", low) for n in names):
                continue
            for rx, status in STATUS_WORDS:
                if re.search(rx, low):
                    return p, status
    return None


def may_change_project(g, person: str | None, project: str) -> bool:
    """The project's owner, a lead, or the owner's manager."""
    if not person:
        return False
    rows = Q.rows(
        g,
        """MATCH (me:Person {id: $me}), (p:Project {id: $p})
           OPTIONAL MATCH (o:Person)-[:OWNS]->(p)
           OPTIONAL MATCH (o)-[rt:REPORTS_TO]->(me)
           RETURN 'leads' IN coalesce(me.groups, []) AS lead, o.id AS owner, rt IS NOT NULL AS manager""",
        me=person,
        p=project,
    )
    return bool(rows) and any(r["lead"] or r["owner"] == person or r["manager"] for r in rows)


def apply_project_status(g, event: Event) -> dict | None:
    """If the message changes a project's status, record it (when its author may) and say what happened."""
    hit = find_status_change(g, event.text)
    if not hit:
        return None
    p, status = hit
    out = {"project": p["id"], "name": p["name"], "from": p["status"], "to": status, "by": event.author, "message": event.id}
    if not may_change_project(g, event.author, p["id"]):
        return {**out, "status": "no-rights"}
    if p["status"] == status:
        return {**out, "status": "unchanged"}
    g.query(
        """MATCH (p:Project {id: $p}), (m:Message {id: $m})
           SET p.status = $s, p.status_by = $by, p.status_at = $at, p.status_ms = $ms, p.status_msg = $m
           MERGE (m)-[r:CHANGES_STATUS]->(p) SET r.to = $s, r.at = $at""",
        {"p": p["id"], "m": event.id, "s": status, "by": event.author, "at": event.ts, "ms": to_ms(event.ts)},
    )
    return {**out, "status": "changed"}


def next_ticket_id(g, prefix: str = "BD") -> str:
    rows = Q.rows(g, "MATCH (t:Ticket) WHERE t.id STARTS WITH $p RETURN t.id AS id", p=f"{prefix}-")
    nums = [int(r["id"].split("-")[1]) for r in rows if r["id"].split("-")[1].isdigit()]
    return f"{prefix}-{max(nums, default=100) + 1}"


def create_ticket(g, title: str, description: str, creator: str, assignee: str | None, project: str | None, ts: str, labels: list[str] | None = None) -> dict:
    """A ticket created in the tracker: written like any ingested ticket, then included in its project."""
    from graph.writer import write_tickets

    tid = next_ticket_id(g)
    # same tracker as the other tickets: its URL follows theirs (…/issue/BD-101 -> …/issue/BD-117)
    like = Q.rows(g, "MATCH (t:Ticket) WHERE t.url CONTAINS t.id RETURN t.id AS id, t.url AS url LIMIT 1")
    url = like[0]["url"].replace(like[0]["id"], tid) if like else ""
    ev = Event(
        source="tickets",
        kind="ticket",
        id=tid,
        author=creator,
        ts=ts,
        text=f"{title}\n\n{description}",
        url=url,
        extra={"title": title, "description": description, "state": "Todo", "labels": labels or [], "assignee": assignee, "updated_at": ts},
    )
    write_tickets(g, [ev])
    included = None
    if project:
        rows = Q.rows(g, "MATCH (p:Project {id: $p}), (t:Ticket {id: $t}) MERGE (p)-[:INCLUDES]->(t) RETURN p.name AS name", p=project, t=tid)
        included = rows[0]["name"] if rows else None
    return {"ticket": tid, "title": title, "creator": creator, "assignee": assignee, "project": project, "project_name": included}
