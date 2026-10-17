"""Graph tools the agent can call. Each returns {"rows": [...], "paths": [...]}.

`paths` are human-readable graph paths: the evidence shown next to every answer.
"""

import re

from graph import queries as Q
from graph.db import get_graph
from pipeline.events import from_ms


class _ReadOnly:
    """The graph as the agent's tools see it: every query goes through FalkorDB's GRAPH.RO_QUERY, so a tool can't
    write even if a query were wrong. Writes happen only through pipeline.work / pipeline.actions, after an owner says so."""

    def __init__(self, g):
        self._g = g

    def query(self, q, params=None, **kw):
        return self._g.ro_query(q, params, **kw)

    def __getattr__(self, name):
        return getattr(self._g, name)


def _g():
    return _ReadOnly(get_graph())


def drift_path(d: dict) -> str:
    p = (
        f"(Person {d['changed_by']})-[:POSTED]->(Message {d['message']} @ {d['source']}#{d['channel']}, {d['changed_at']})"
        f"-[:CHANGES]->(Requirement \"{d['requirement_text']}\")-[:AMENDS]->(Ticket {d['ticket']})"
        f"-[:ABOUT]->(Feature {d['feature']})"
    )
    stale = [x for x in d["stale_prs"] if x["pr"] is not None]
    if stale:
        p += " ; " + " ; ".join(
            f"(PullRequest #{x['pr']})-[:REFERENCES]->(Ticket {d['ticket']})"
            + f", {x['label']}"
            + (f", IMPLEMENTS older \"{x['implements']}\"" if x.get("implements") else "")
            for x in stale
        )
    for doc in d.get("stale_docs", []):
        p += f" ; (Document {doc['id']} \"{doc['title']}\", updated {(doc['updated'] or '')[:10]})-[:MENTIONS]->(Ticket {d['ticket']}), older than the change"
    return p


def list_features() -> dict:
    rows = Q.rows(
        _g(),
        """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                           RETURN f.id AS id, f.name AS name, collect(t.id) AS tickets ORDER BY f.id""",
    )
    return {"rows": rows, "paths": [f"(Feature {r['id']}) <-[:ABOUT]- tickets {r['tickets']}" for r in rows]}


def drift_for_feature(feature: str | None = None) -> dict:
    rows = Q.drift(_g(), feature=feature)
    return {"rows": rows, "paths": [drift_path(d) for d in rows]}


def decision_history(feature: str) -> dict:
    rows = Q.rows(_g(), Q.DECISION_HISTORY, feature=feature)
    paths = []
    for r in rows:
        rel = "STATES" if r["origin"] == "ticket" else "CHANGES"
        p = f"({r['source_type']} {r['source_id']})-[:{rel}]->(Requirement {r['requirement']} @ {r['at']})"
        if r["supersedes"]:
            p += f"-[:SUPERSEDES]->(Requirement {r['supersedes']})"
        if r["implemented_by"]:
            p += f" <-[:IMPLEMENTS]- PR {r['implemented_by']}"
        paths.append(p)
    return {"rows": rows, "paths": paths}


def feature_timeline(feature: str) -> dict:
    rows = Q.rows(_g(), Q.FEATURE_TIMELINE, feature=feature)
    for r in rows:
        r["at"] = from_ms(r.pop("at"))
    rows = [r for r in rows if r["type"] != "Message" or len(r["text"] or "") > 25][:60]
    return {"rows": rows, "paths": [f"({r['type']} {r['id']})-[:ABOUT]->(Feature {feature})" for r in rows]}


def who_knows(feature: str) -> dict:
    rows = Q.rows(_g(), Q.WHO_KNOWS, feature=feature)
    return {"rows": rows, "paths": [f"(Person {r['person']})-[:POSTED|AUTHORED|MADE]->({r['items']} items)-[:ABOUT]->(Feature {feature})" for r in rows]}


def decision_impact(decision: str) -> dict:
    rows = Q.rows(_g(), Q.DECISION_IMPACT, decision=decision)
    return {
        "rows": rows,
        "paths": [
            f"(Decision {decision})-[:CHANGES]->(Requirement)-[:AMENDS]->(Ticket {r['ticket']}) " f"<-[:REFERENCES]- PRs {r['prs']}; owner {r['owner']}"
            for r in rows
        ],
    }


def list_decisions(feature: str | None = None) -> dict:
    rows = Q.rows(
        _g(),
        """MATCH (p:Person)-[:MADE]->(d:Decision)-[:CHANGES]->(r:Requirement)-[:ABOUT]->(f:Feature)
                           WHERE $feature IS NULL OR f.id = $feature
                           MATCH (d)-[:RECORDED_IN]->(m:Message)
                           RETURN d.id AS id, d.text AS text, d.at AS at, p.id AS by, f.id AS feature,
                                  m.source AS platform, m.channel AS channel, m.url AS url ORDER BY d.at_ms""",
        feature=feature,
    )
    return {
        "rows": rows,
        "paths": [f"(Person {r['by']})-[:MADE]->(Decision {r['id']})-[:RECORDED_IN]->(Message @ {r['platform']}#{r['channel']})" for r in rows],
    }


def how_connected(a: str, b: str) -> dict:
    """Shortest causal chain between two ids (person, message, ticket BD-.., PR-n, decision dec:..)."""
    rows = Q.connection(_g(), a, b)
    paths = []
    for r in rows:
        parts = [f"({r['nodes'][0]['type']} {r['nodes'][0]['id']})"]
        for i, rel in enumerate(r["rels"]):
            nxt = r["nodes"][i + 1]
            forward = r["starts"][i] == r["nodes"][i]["id"]
            parts.append((f"-[:{rel}]->" if forward else f"<-[:{rel}]-") + f"({nxt['type']} {nxt['id']})")
        paths.append("".join(parts))
    return {"rows": rows, "paths": paths}


def feature_prs(feature: str) -> dict:
    """PRs about a feature: their ticket, how the link was made, author, merge date, what they implement."""
    rows = Q.rows(
        _g(),
        """MATCH (pr:PullRequest)-[:ABOUT]->(:Feature {id: $f}) MATCH (a:Person)-[:AUTHORED]->(pr)
                           OPTIONAL MATCH (pr)-[ref:REFERENCES]->(t:Ticket)
                           OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(r:Requirement)
                           RETURN pr.number AS pr, pr.title AS title, pr.url AS url, a.id AS author, pr.merged AS merged,
                                  collect(DISTINCT t.id) AS tickets, collect(DISTINCT coalesce(ref.how, 'hard')) AS link,
                                  collect(DISTINCT r.id) AS implements, pr.number AS n ORDER BY n""",
        f=feature,
    )
    return {
        "rows": rows,
        "paths": [f"(PullRequest #{r['pr']})-[:REFERENCES {{via: {', '.join(r['link'])}}}]->(Ticket {', '.join(r['tickets']) or '?'})" for r in rows],
    }


def search_knowledge(query: str) -> dict:
    """Semantic search over document chunks (FalkorDB vector index), limited to what the viewer may see."""
    from pipeline.access import current_viewer
    from pipeline.knowledge import search

    rows = search(get_graph(), query, current_viewer())
    return {
        "rows": rows,
        "paths": [f"(Person {r['author']})-[:AUTHORED]->(Document {r['doc']})-[:HAS_CHUNK]->(Chunk {r['chunk']})" for r in rows],
    }


def ticket_owners(ticket: str) -> dict:
    """Who owns a ticket: its creator and its assignee (both may change its requirement)."""
    rows = Q.rows(
        _g(),
        """MATCH (t:Ticket {id: $t}) OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person)
           RETURN t.id AS ticket, t.title AS title, c.id AS creator, c.name AS creator_name, a.id AS assignee, a.name AS assignee_name""",
        t=ticket,
    )
    return {"rows": rows, "paths": [f"(Person {r['creator']})-[:AUTHORED]->(Ticket {r['ticket']})-[:ASSIGNED_TO]->(Person {r['assignee']})" for r in rows]}


def list_projects() -> dict:
    """Projects with their status (active, on hold, cancelled: and the chat message that changed it), launch dates,
    owners, tickets, features and the client deliverables that need them."""
    from pipeline.impact import projects

    g = _g()
    rows = projects(g)
    msgs = {
        r["id"]: r
        for r in Q.rows(
            g,
            "MATCH (m:Message)-[:CHANGES_STATUS]->(:Project) RETURN m.id AS id, m.text AS text, m.source AS source, m.channel AS channel",
        )
    }
    paths = []
    for r in rows:
        m = msgs.get(r["status_msg"] or "")
        r["status_text"], r["status_where"] = (m["text"], f"{(m['source'] or 'chat').capitalize()} #{m['channel']}") if m else (None, None)
        if m:
            paths.append(
                f"(Person {r['status_by']})-[:POSTED]->(Message {m['id']} @ {m['source']}#{m['channel']}, {(r['status_at'] or '')[:10]})"
                f"-[:CHANGES_STATUS]->(Project {r['id']})"
            )
        elif r["owner"]:
            paths.append(f"(Person {r['owner']})-[:OWNS]->(Project {r['id']})" + (f"-[:INCLUDES]->(Ticket {r['tickets'][0]})" if r["tickets"] else ""))
    return {"rows": rows, "paths": paths}


STUCK = re.compile(r"\b(delay(ed|s)?|blocked|on hold|waiting (on|for)|ooo|out of (the )?office|stuck)\b", re.I)


def why_blocked(topic: str) -> dict:
    """Why a piece of work is stuck and who can approve an override, across four systems: the chat message that points
    at a doc (Slack/Discord), the doc that names the ticket (Notion/Drive), the ticket and its assignee (tracker), and the
    assignee's HR record (time off, manager)."""
    from pipeline.textsim import TfIdf

    g = _g()
    tickets = Q.rows(g, "MATCH (t:Ticket) RETURN t.id AS id, t.title AS title, t.description AS description, t.state AS state")
    named = {m.upper() for m in re.findall(r"\b[A-Z]{2,6}-\d+\b", topic or "", re.I)}
    stuck = [t["id"] for t in tickets if t["state"] == "Blocked" or STUCK.search(t["description"] or "")]
    if named:
        pick = [t for t in sorted(named) if any(x["id"] == t for x in tickets)]
    elif stuck:
        # match on what is stuck, not on the words that say it's stuck ("delayed" alone would match any delayed ticket)
        what = re.sub(r"\b(override|approve|unblock|sign off|who|why)\b", " ", STUCK.sub(" ", topic or ""), flags=re.I)
        best, score = TfIdf({t["id"]: f"{t['title']} {t['description']}" for t in tickets}).best(what, among=stuck)
        pick = [best] if best and score >= 0.08 else []
    else:
        pick = []
    rows, paths = [], []
    for tid in pick:
        t = Q.rows(
            g,
            """MATCH (t:Ticket {id: $t})
               OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person) OPTIONAL MATCH (a)-[:REPORTS_TO]->(mgr:Person)
               OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t)
               RETURN t.id AS ticket, t.title AS title, t.state AS state, t.description AS description,
                      a.id AS assignee, a.name AS assignee_name, a.ooo_from AS ooo_from, a.ooo_until AS ooo_until, a.ooo_kind AS ooo_kind,
                      mgr.id AS manager, mgr.name AS manager_name, coalesce(mgr.title, mgr.role) AS manager_title, c.id AS creator""",
            t=tid,
        )[0]
        docs = Q.rows(
            g,
            """MATCH (d:Document)-[:MENTIONS]->(:Ticket {id: $t}) OPTIONAL MATCH (au:Person)-[:AUTHORED]->(d)
               RETURN d.id AS id, d.title AS title, d.source AS source, au.id AS author ORDER BY id""",
            t=tid,
        )
        msgs = Q.rows(
            g,
            """MATCH (p:Person)-[:POSTED]->(m:Message)-[:REFERS_TO]->(d:Document)-[:MENTIONS]->(:Ticket {id: $t})
               RETURN m.id AS id, m.text AS text, m.source AS source, m.channel AS channel, m.ts AS ts, p.id AS author, d.id AS doc
               ORDER BY m.ts_ms DESC LIMIT 3""",
            t=tid,
        )
        reason = next((s.rstrip(" .;") for s in re.split(r"(?<=[.;])\s+", t["description"] or "") if STUCK.search(s)), None)
        ooo = {"from": t["ooo_from"], "until": t["ooo_until"], "kind": t["ooo_kind"]} if t["ooo_until"] else None
        rows.append(
            {
                **{k: t[k] for k in ("ticket", "title", "state", "assignee", "assignee_name", "manager", "manager_name", "manager_title", "creator")},
                "reason": reason,
                "out_of_office": ooo,
                "can_override": [p for p in dict.fromkeys([t["manager"], t["creator"]]) if p],
                "docs": docs,
                "messages": msgs,
            }
        )
        tail = f"(Ticket {tid})" + (f"-[:ASSIGNED_TO]->(Person {t['assignee']})" if t["assignee"] else "")
        tail += f"-[:REPORTS_TO]->(Person {t['manager']})" if t["manager"] else ""
        if msgs:
            m = msgs[0]
            paths.append(
                f"(Person {m['author']})-[:POSTED]->(Message {m['id']} @ {m['source']}#{m['channel']}, {(m['ts'] or '')[:10]})-[:REFERS_TO]->(Document {m['doc']})-[:MENTIONS]->{tail}"
            )
        elif docs:
            paths.append(f"(Document {docs[0]['id']})-[:MENTIONS]->{tail}")
        else:
            paths.append(tail)
    return {"rows": rows, "paths": paths}


def impact_of_delay(target: str, days: int = 14) -> dict:
    """What a delay ripples into: downstream projects (through BLOCKS chains), client deliverables and the teams doing the work."""
    from pipeline.impact import impact_of_delay as run

    out = run(_g(), target, int(days or 14))
    out.pop("graph", None)
    return {"rows": [out] if out.get("target") else [], "paths": out.get("paths", [])}


def plan_fix(ticket: str) -> dict:
    """What has to change to close the open drift on a ticket, and who owns each part (read-only)."""
    from pipeline.work import plan

    g = _g()
    on = sorted((d for d in Q.drift(g, ticket=ticket)), key=lambda d: -d["changed_ms"])
    if not on:
        return {"rows": [], "paths": []}
    p = plan(g, on[0]["requirement"])
    rows = [{**i, "decided_by": p["decided_by"], "can_approve": p["can_apply"]} for i in p["items"]]
    paths = [drift_path(p["drift"])] + [f"(Person {i['assignee']})-[:AUTHORED]->({i['target']})" for i in p["items"] if i["kind"] != "ticket"]
    return {"rows": rows + [{"kind": "tell", "people": p["tell"]}], "paths": paths}


def follow_ups(person: str | None = None) -> dict:
    """Open follow-up tasks (opened when an owner applied a fix plan), optionally for one person."""
    from pipeline.work import tasks

    rows = tasks(_g(), person=person)
    return {
        "rows": rows,
        "paths": [
            f"(Person {r['approved_by']})-[:APPROVED]->(Task T-{r['num']})-[:ASSIGNED_TO]->(Person {r['assignee']}) ; (Task T-{r['num']})-[:FIXES]->({r['target']})"
            for r in rows
        ],
    }


TOOLS = {
    "list_features": (list_features, "List all features with their tickets. Call first to find feature ids.", {}),
    "drift_for_feature": (
        drift_for_feature,
        "Requirements changed in chat that the ticket/PRs don't reflect. Omit feature for all.",
        {"feature": {"type": "string", "description": "feature id, optional"}},
    ),
    "decision_history": (
        decision_history,
        "How a feature's requirements evolved: every ticket version and chat change, what superseded what, which PR implements which.",
        {"feature": {"type": "string"}},
    ),
    "feature_timeline": (feature_timeline, "Chronological messages, tickets, PRs and requirements for a feature.", {"feature": {"type": "string"}}),
    "who_knows": (who_knows, "People ranked by involvement with a feature (decisions, PRs, tickets, messages).", {"feature": {"type": "string"}}),
    "list_decisions": (
        list_decisions,
        "Decisions made in chat, optionally for one feature, with who made them and where.",
        {"feature": {"type": "string", "description": "feature id, optional"}},
    ),
    "feature_prs": (
        feature_prs,
        "Pull requests for a feature: ticket, how the link was resolved (hard id vs. proximity), author, merge date, implemented requirement.",
        {"feature": {"type": "string"}},
    ),
    "how_connected": (
        how_connected,
        "Shortest causal chain linking two things, e.g. a person and a PR ('liam', 'PR-6') or a message and a ticket. Ids: person ids, message ids, BD-xxx, PR-n, dec:<message id>.",
        {"a": {"type": "string"}, "b": {"type": "string"}},
    ),
    "decision_impact": (
        decision_impact,
        "Downstream impact of a decision: ticket, owner, PRs, related tickets.",
        {"decision": {"type": "string", "description": "decision id like dec:m_exp_12"}},
    ),
    "search_knowledge": (
        search_knowledge,
        "Search the company's documents (PRDs, design notes, policies) by meaning. Returns passages with their document and author. Only returns what the person asking may see.",
        {"query": {"type": "string"}},
    ),
    "ticket_owners": (
        ticket_owners,
        "Who owns a ticket: the person who created it and the person assigned to it. Both count as owners.",
        {"ticket": {"type": "string", "description": "ticket id like BD-101"}},
    ),
    "list_projects": (
        list_projects,
        "Projects (e.g. Project Alpha) with their status (active, on hold, cancelled, and the chat message that changed it), launch dates, owners, tickets, features and the client deliverables that need them. Use it for 'which projects are active?'.",
        {},
    ),
    "why_blocked": (
        why_blocked,
        "Why a piece of work is delayed or blocked and who can approve an override: follows chat -> the doc it points to -> the ticket that doc names -> its assignee's HR record (out of office) -> their manager.",
        {"topic": {"type": "string", "description": "what is stuck, e.g. 'database migration', or a ticket id"}},
    ),
    "impact_of_delay": (
        impact_of_delay,
        "Impact of delaying a project, feature or ticket by N days: which projects slip downstream (through ticket BLOCKS chains), which client deliverables miss or get tight, and which teams and people are affected.",
        {
            "target": {"type": "string", "description": "project id or name (e.g. 'alpha' or 'Project Alpha'), feature id, or ticket id"},
            "days": {"type": "integer", "description": "delay in days, e.g. 14 for two weeks"},
        },
    ),
    "plan_fix": (
        plan_fix,
        "What has to change to close the drift on a ticket and who owns each part: the ticket, each PR that shipped the old version (its author), each stale doc (its author), who else to tell, and who can approve.",
        {"ticket": {"type": "string", "description": "ticket id like BD-103"}},
    ),
    "follow_ups": (
        follow_ups,
        "Open follow-up tasks created when an owner approved a fix, with assignee, approver and the PR or doc each one fixes.",
        {"person": {"type": "string", "description": "person id, optional"}},
    ),
}


def openai_schema() -> list[dict]:
    out = []
    for name, (_, desc, props) in TOOLS.items():
        required = [k for k, v in props.items() if "optional" not in v.get("description", "")]
        out.append(
            {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": required}}}
        )
    return out


def call(name: str, args: dict) -> dict:
    """Runs a tool, then drops every row and path that mentions a node the current viewer may not see
    (pipeline.access), so neither the LLM nor the rules agent ever receives restricted content."""
    from pipeline.access import current_viewer, hidden, redact

    fn = TOOLS[name][0]
    out = fn(**{k: v for k, v in (args or {}).items() if k in TOOLS[name][2]})
    return redact(out, hidden(get_graph(), current_viewer()))
