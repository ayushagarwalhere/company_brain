"""MCP server: the company's context for coding agents.

An agent asked to "implement BD-101" reads the ticket. The ticket is often out of date: the team changed the
requirement in Slack afterwards. These tools give any MCP client (Claude Code, Cursor, ...) what the graph knows:

    current_spec(ticket)      what to build now: the newest requirement, who decided it, where and when, what the
                              ticket still says, which PRs and docs carry the old version, who owns it
    drift(feature?)           requirements changed in chat that tickets and PRs don't reflect yet
    who_knows(topic)          people ranked by their involvement with a feature or ticket
    decision_history(topic)   how the requirements evolved: each version, its source, what replaced what
    impact(target, days)      what a delay ripples into: downstream projects, client deliverables, teams
    find(query)               ticket and feature ids from a few words

Each one is a thin wrapper over agent/tools.py: read-only (GRAPH.RO_QUERY) and redacted for the viewer, like the API.

    stdio (local)   python -m agent.mcp_server          BRAIN_ORG selects the org's graph, BRAIN_USER the viewer
    HTTP (hosted)   the API serves it at /mcp           X-Org / X-User headers, or ?org= / ?as=

    claude mcp add company-brain -- python -m agent.mcp_server
    claude mcp add --transport http company-brain https://<host>/mcp
"""

import os
import re
from contextlib import contextmanager
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from agent import tools
from graph import queries as Q

INSTRUCTIONS = """The company's context graph: tickets, pull requests, Slack and Discord decisions, docs and people, linked.
Ticket text is often out of date, because teams change requirements in chat after the ticket was written.
Before you implement, estimate, review or plan a ticket (ids like BD-101, ENG-12, GH-7), call current_spec with its id
and build what it returns as current_requirement, not the ticket's text. Say in your summary or PR description which
decision you followed (who, where, when). If you don't know the ticket id, call find first."""

server: MCPServer = MCPServer(name="company-brain", title="Company Brain", instructions=INSTRUCTIONS, version="1.0")

TICKET = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-\d{1,6}$")


@contextmanager
def _scope(ctx: Context | None):
    """The org and the viewer of this call: from the HTTP request when there is one, else from the environment."""
    from graph.db import _org, set_org
    from pipeline.access import reset_viewer, set_viewer

    req = None
    try:
        req = ctx.request_context.request if ctx is not None else None
    except Exception:  # noqa: BLE001 - no request (stdio, or called directly)
        req = None
    if req is not None and hasattr(req, "headers"):
        params = getattr(req, "query_params", {}) or {}
        org = req.headers.get("x-org") or params.get("org")
        viewer = req.headers.get("x-user") or params.get("as")
    else:
        org, viewer = os.getenv("BRAIN_ORG"), os.getenv("BRAIN_USER")
    t_org = set_org(org or None)
    t_viewer = set_viewer(viewer or None)
    try:
        yield
    finally:
        reset_viewer(t_viewer)
        _org.reset(t_org)


def _redact(out: dict) -> dict:
    from graph.db import get_graph
    from pipeline.access import current_viewer, hidden, redact

    return redact(out, hidden(get_graph(), current_viewer()))


def _people(g, ids: list[str]) -> dict[str, dict]:
    rows = Q.rows(g, "MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.name AS name, coalesce(p.title, p.role) AS role", ids=ids)
    return {r["id"]: r for r in rows}


def _feature(g, topic: str) -> dict | None:
    """A feature from a ticket id, a feature id or name, or a few words."""
    from pipeline.textsim import TfIdf

    topic = (topic or "").strip()
    if TICKET.match(topic):
        r = Q.rows(g, "MATCH (:Ticket {id: $t})-[:ABOUT]->(f:Feature) RETURN f.id AS id, f.name AS name LIMIT 1", t=topic.upper())
        if r:
            return r[0]
    r = Q.rows(g, "MATCH (f:Feature) WHERE f.id = $x OR toLower(f.name) = toLower($x) RETURN f.id AS id, f.name AS name LIMIT 1", x=topic)
    if r:
        return r[0]
    feats = Q.rows(g, "MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f) RETURN f.id AS id, f.name AS name, collect(t.title) AS titles")
    if not feats or not topic:
        return None
    best, score = TfIdf({f["id"]: f"{f['name']} {' '.join(f['titles'])}" for f in feats}).best(topic)
    return next(({"id": f["id"], "name": f["name"]} for f in feats if f["id"] == best), None) if best and score >= 0.1 else None


SOURCES = {"slack": "Slack", "discord": "Discord", "github": "GitHub", "jira": "Jira", "linear": "Linear"}


def _where(d: dict) -> str:
    src = d.get("source") or "chat"
    return f"{SOURCES.get(src, src.capitalize())} #{d.get('channel') or '?'}"


def spec(ticket: str) -> dict:
    """current_spec without the MCP plumbing (the HTTP route and the tests call it too)."""
    g = tools._g()
    tid = (ticket or "").strip().upper()
    found = Q.rows(
        g,
        """MATCH (t:Ticket {id: $t}) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
           OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person)
           RETURN t.id AS id, t.title AS title, t.description AS description, t.state AS state, t.url AS url,
                  f.id AS feature, f.name AS feature_name, c.id AS creator, c.name AS creator_name, a.id AS assignee, a.name AS assignee_name
           LIMIT 1""",
        t=tid,
    )
    if not found:
        return {"found": False, "ticket": tid, "summary": f"There is no ticket {tid} in the company graph.", "similar": find(ticket)["tickets"][:5]}
    t = found[0]
    open_changes = sorted(Q.drift(g, ticket=tid), key=lambda d: d["changed_ms"])
    current = Q.rows(
        g,
        """MATCH (r:Requirement {ticket: $t})
           WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement) AND NOT (:Decision)-[:DISMISSES]->(r)
           OPTIONAL MATCH (src)-[:STATES|CHANGES]->(r)
           OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(r)
           RETURN r.id AS id, r.text AS text, r.at AS at, r.origin AS origin, labels(src)[0] AS source_type, src.id AS source_id,
                  collect(DISTINCT pr.number) AS implemented_by, r.at_ms AS at_ms ORDER BY at_ms""",
        t=tid,
    )
    versions: dict[str, dict] = {}  # one row per requirement version (a chat change is reached from its Message and its Decision)
    for r in Q.rows(g, Q.DECISION_HISTORY, feature=t["feature"]):
        if r["ticket"] == tid and r["requirement"] not in versions:
            versions[r["requirement"]] = {
                "at": (r["at"] or "")[:10],
                "requirement": r["text"],
                "from": f"{r['source_type']} {r['source_id']}",
                "replaces": r["supersedes"],
            }
    history = list(versions.values())
    owners = [p for p in dict.fromkeys([t["creator"], t["assignee"]]) if p]
    ask = [
        {"person": r["person"], "name": r["name"], "role": r["role"], "items": r["items"]}
        for r in (Q.rows(g, Q.WHO_KNOWS, feature=t["feature"])[:3] if t["feature"] else [])
    ]
    out: dict[str, Any] = {"found": True, "ticket": tid, "title": t["title"], "url": t["url"], "state": t["state"]}
    if open_changes:
        latest = open_changes[-1]
        who = _people(g, [d["changed_by"] for d in open_changes])
        by = who.get(latest["changed_by"], {"name": latest["changed_by"], "role": None})
        stale_prs = [
            {"pr": p["pr"], "title": p["title"], "url": p["url"], "merged": p["merged"], "note": p["label"], "built": p.get("implements")}
            for p in latest["stale_prs"]
        ]
        out |= {
            "status": "TICKET_OUT_OF_DATE",
            "summary": (
                f"{tid}'s ticket text is out of date. Build the requirement {by['name']}"
                + (f" ({by['role']})" if by.get("role") else "")
                + f" decided in {_where(latest)} on {(latest['changed_at'] or '')[:10]}, not the ticket text."
                + (f" PR #{stale_prs[0]['pr']} already shipped the old version: change it rather than building beside it." if stale_prs else "")
            ),
            "current_requirement": latest["requirement_text"],
            "ticket_still_says": latest["ticket_text"],
            "decided": {
                "by": latest["changed_by"],
                "name": by["name"],
                "role": by.get("role"),
                "at": latest["changed_at"],
                "where": _where(latest),
                "message": latest["message_text"],
                "link": latest["message_url"],
            },
            "earlier_open_changes": [
                {
                    "requirement": d["requirement_text"],
                    "by": who.get(d["changed_by"], {}).get("name", d["changed_by"]),
                    "where": _where(d),
                    "at": d["changed_at"],
                }
                for d in open_changes[:-1]
            ],
            "shipped_old_version": stale_prs,
            "stale_docs": [{"id": x["id"], "title": x["title"], "updated": (x["updated"] or "")[:10]} for x in latest["stale_docs"]],
            "next_steps": [
                f"Implement current_requirement. In the PR description, cite the decision: {by['name']}, {_where(latest)}, {(latest['changed_at'] or '')[:10]}.",
                *(f"Update PR #{p['pr']} ({p['title']}): it implements the old requirement." for p in stale_prs),
                f"Ask the ticket owner ({', '.join(owners) or 'unassigned'}) to update {tid}'s text, or use 'Write to ticket' on the dashboard.",
            ],
            "evidence": [tools.drift_path(d) for d in open_changes],
        }
    else:
        newest = current[-1] if current else None
        out |= {
            "status": "CURRENT",
            "summary": f"{tid}'s ticket matches the latest requirement the graph knows of: no later change in chat, PRs or docs.",
            "current_requirement": newest["text"] if newest else t["description"],
            "implemented_by": newest["implemented_by"] if newest else [],
            "evidence": [f"(Requirement {newest['id']} @ {(newest['at'] or '')[:10]}) <-[:STATES|CHANGES]- ({newest['source_type']} {newest['source_id']})"]
            if newest
            else [],
        }
    out |= {"owners": owners, "people_to_ask": ask, "history": history, "feature": {"id": t["feature"], "name": t["feature_name"]}}
    from graph.db import current_org
    from pipeline import tryrepo

    if tryrepo.is_repo_org(current_org()) and open_changes:
        # a public repo tried from the site: rules extraction on real text, so a candidate to read, not a fact
        out["caveat"] = tryrepo.NOTE
        out["checked_before"] = tryrepo._known_labels().get(open_changes[-1]["message_url"])
    return out


def find(query: str) -> dict:
    """Tickets and features whose id, title or text match a few words, best first."""
    from pipeline.textsim import TfIdf

    g = tools._g()
    q = (query or "").strip()
    rows = Q.rows(
        g,
        """MATCH (t:Ticket) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
           RETURN t.id AS id, t.title AS title, t.state AS state, t.description AS description, f.id AS feature, f.name AS feature_name""",
    )
    exact = [r for r in rows if r["id"] == q.upper()]
    scores = TfIdf({r["id"]: f"{r['id']} {r['title']} {r['description'] or ''}" for r in rows}).scores(q) if rows and q else {}
    ranked = exact + sorted((r for r in rows if scores.get(r["id"], 0) > 0.05 and r not in exact), key=lambda r: -scores[r["id"]])
    tickets = [{"ticket": r["id"], "title": r["title"], "state": r["state"], "feature": r["feature"]} for r in ranked[:10]]
    feats = list({r["feature"]: {"feature": r["feature"], "name": r["feature_name"]} for r in ranked[:10] if r["feature"]}.values())
    return {"tickets": tickets, "features": feats}


def _run(ctx: Context | None, fn) -> dict:
    """One tool call: in the caller's org and as its viewer, on a graph that exists, redacted for that viewer."""
    with _scope(ctx):
        from graph.db import current_graph_name, current_org, get_db

        if current_graph_name() not in get_db().list_graphs():
            return {"found": False, "note": f"Org {current_org()!r} has no graph yet: connect its tools on the dashboard first."}
        return _redact(fn())


def _open_drift(feature: str | None) -> dict:
    g = tools._g()
    f = _feature(g, feature) if feature else None
    if feature and not f:
        return {"drift": [], "note": f"No feature matches {feature!r}; call find."}
    rows = Q.drift(g, feature=f["id"] if f else None)
    return {
        "drift": [
            {
                "ticket": d["ticket"],
                "feature": d["feature_name"],
                "ticket_says": d["ticket_text"],
                "decided": d["requirement_text"],
                "by": d["changed_by"],
                "where": _where(d),
                "at": d["changed_at"],
                "shipped_old_version": [p["pr"] for p in d["stale_prs"]],
                "stale_docs": [x["id"] for x in d["stale_docs"]],
            }
            for d in rows
        ],
        "evidence": [tools.drift_path(d) for d in rows],
    }


def _about(topic: str, key: str, fn, limit: int | None = None) -> dict:
    """Runs a feature-level tool for a ticket id, a feature or a few words."""
    f = _feature(tools._g(), topic)
    if not f:
        return {key: [], "note": f"No feature matches {topic!r}; call find."}
    out = fn(f["id"])
    return {"feature": f, key: out["rows"][:limit], "evidence": out["paths"][:limit]}


@server.tool()
def current_spec(ticket: str, ctx: Context) -> dict:
    """What to build for a ticket right now. Call this before implementing, estimating or reviewing any ticket.

    Returns the newest requirement (which may have been decided in Slack or Discord after the ticket was written), who
    decided it, where and when, what the ticket still says, PRs that already shipped the old version, stale docs, the
    ticket's owners, the people who know the feature best, and the graph paths behind each fact.

    Args:
        ticket: ticket id, e.g. BD-101, ENG-12 or GH-7
    """
    return _run(ctx, lambda: spec(ticket))


@server.tool()
def drift(ctx: Context, feature: str | None = None) -> dict:
    """Requirements changed in chat that the ticket, the PRs and the docs don't reflect yet (the open drift).

    Args:
        feature: optional feature id, feature name or ticket id; omit for all open drift
    """
    return _run(ctx, lambda: _open_drift(feature))


@server.tool()
def who_knows(topic: str, ctx: Context) -> dict:
    """People ranked by their involvement with a feature: decisions, PRs, tickets and messages about it.

    Args:
        topic: a ticket id (BD-101), a feature id or name, or a few words ("csv export")
    """
    return _run(ctx, lambda: _about(topic, "people", tools.who_knows, 8))


@server.tool()
def decision_history(topic: str, ctx: Context) -> dict:
    """How a feature's requirements evolved: every ticket version and chat decision in order, what replaced what, and
    which PR implements which version.

    Args:
        topic: a ticket id (BD-101), a feature id or name, or a few words
    """
    return _run(ctx, lambda: _about(topic, "history", tools.decision_history))


@server.tool()
def impact(target: str, ctx: Context, days: int = 14) -> dict:
    """What delaying a project, feature or ticket by N days ripples into: downstream projects (through ticket BLOCKS
    chains), client deliverables that miss or get tight, and the teams and people affected.

    Args:
        target: project id or name ("Project Alpha"), feature id or ticket id
        days: the delay in days (14 = two weeks)
    """

    def run() -> dict:
        out = tools.impact_of_delay(target, days)
        return {"impact": out["rows"][0] if out["rows"] else None, "evidence": out["paths"]}

    return _run(ctx, run)


@server.tool(name="find")
def find_tool(query: str, ctx: Context) -> dict:
    """Ticket and feature ids from a few words, best match first. Use it when you don't know the ticket id.

    Args:
        query: words from the ticket or feature, e.g. "csv export" or "sla alerts"
    """
    return _run(ctx, lambda: find(query))


def http_app():
    """The streamable-HTTP transport, mounted by api/main.py at /mcp. Stateless JSON: every call stands alone, so it
    scales like the rest of the API. DNS-rebinding protection is off because the server is meant to be reached by
    its public host name; it is read-only and serves exactly what the read API serves."""
    from mcp.server.transport_security import TransportSecuritySettings

    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def main() -> None:
    server.run()  # stdio


if __name__ == "__main__":
    main()
