"""Live updates from tickets and GitHub: keep the graph current as work changes.

ticket_updated  a ticket's description changed -> new Requirement version (STATES), then the
                ticket's SUPERSEDES chain is recomputed with the extractor's reflects() check, so
                an edit that carries the chat change resolves drift and an unrelated edit does not.
pr_event        a GitHub pull_request webhook payload -> PullRequest node, ticket links (hard refs),
                feature, IMPLEMENTS via the extractor, then drift is re-checked for those tickets.
"""
import hashlib
import hmac
from datetime import datetime, timezone

from graph import queries as Q
from graph.writer import write_pull_requests
from pipeline.events import find_ticket_refs, from_ms, to_ms
from pipeline.resolve import supersession_pairs


def _extractor():
    from pipeline import llm
    from pipeline.extract import get_extractor
    return get_extractor("deepseek" if llm.available() else "heuristic")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _drift_ids(g, ticket: str) -> set[str]:
    return {d["requirement"] for d in Q.drift(g, ticket=ticket)}


def recompute_supersession(g, ticket: str, ex=None) -> int:
    """Rebuild SUPERSEDES among one ticket's requirements (ticket versions + chat changes)."""
    ex = ex or _extractor()
    chain = Q.rows(g, """MATCH (q:Requirement {ticket: $t})
                         RETURN q.id AS id, q.text AS text, q.origin AS origin, q.at AS at, q.at_ms AS at_ms
                         ORDER BY q.at_ms, q.id""", t=ticket)
    g.query("MATCH (a:Requirement {ticket: $t})-[s:SUPERSEDES]->(b:Requirement {ticket: $t}) DELETE s", {"t": ticket})
    pairs = supersession_pairs(chain, ex.reflects)
    g.query("""UNWIND $ps AS p MATCH (n:Requirement {id: p.new}), (o:Requirement {id: p.old})
               MERGE (n)-[:SUPERSEDES]->(o)""", {"ps": pairs})
    return len(pairs)


def ticket_updated(g, ticket: str, description: str, actor: str = "maya", at: str | None = None) -> dict:
    t = Q.rows(g, "MATCH (t:Ticket {id: $t}) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature) "
                  "RETURN t.versions AS v, t.version_times AS vt, t.description AS d, f.id AS f", t=ticket)
    if not t:
        raise ValueError(f"unknown ticket {ticket}")
    t = t[0]
    if (description or "").strip() == (t["d"] or "").strip():
        return {"status": "unchanged", "ticket": ticket}
    before = _drift_ids(g, ticket)
    at = at or _now_iso()
    ms = to_ms(at)
    versions, times = list(t["v"] or []), list(t["vt"] or [])
    rid = f"req:{ticket}:v{len(versions) + 1}"
    g.query("""MATCH (t:Ticket {id: $t})
               MERGE (q:Requirement {id: $rid})
               SET q.text = $text, q.at_ms = $ms, q.at = $at, q.origin = 'ticket', q.ticket = $t, q.written_by = $actor
               MERGE (t)-[:STATES {at_ms: $ms}]->(q)
               SET t.description = $text, t.desc_updated_ms = $ms, t.updated = $at, t.updated_ms = $ms,
                   t.versions = $versions, t.version_times = $times""",
            {"t": ticket, "rid": rid, "text": description, "ms": ms, "at": at, "actor": actor,
             "versions": versions + [description], "times": times + [ms]})
    if t["f"]:
        g.query("MATCH (q:Requirement {id: $rid}), (f:Feature {id: $f}) MERGE (q)-[:ABOUT]->(f)", {"rid": rid, "f": t["f"]})
    recompute_supersession(g, ticket)
    after = _drift_ids(g, ticket)
    return {"status": "updated", "ticket": ticket, "version": rid, "resolved": sorted(before - after),
            "still_drifting": sorted(after), "new_drift": sorted(after - before)}


def verify_github_signature(secret: str, body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256: sha256=<hex HMAC of the raw body>."""
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header.split("=", 1)[1])


def pr_event(g, payload: dict) -> dict:
    """Handles a GitHub `pull_request` webhook payload (opened / edited / closed+merged)."""
    from connectors.github import _event
    pr = payload.get("pull_request") or {}
    if not pr.get("number"):
        raise ValueError("not a pull_request payload")
    ev = _event(pr["number"], pr.get("title", ""), pr.get("body") or "", pr.get("html_url", ""),
                "merged" if pr.get("merged_at") else pr.get("state", "open"),
                (pr.get("user") or {}).get("login", "unknown"), pr.get("created_at") or _now_iso(), pr.get("merged_at"))
    tickets = find_ticket_refs(ev.text)
    before = {t: _drift_ids(g, t) for t in tickets}
    write_pull_requests(g, [ev])
    g.query("""MATCH (pr:PullRequest {id: $id})-[:REFERENCES]->(:Ticket)-[:ABOUT]->(f:Feature)
               MERGE (pr)-[:ABOUT {via: 'hard'}]->(f)""", {"id": ev.id})
    ex = _extractor()
    cutoff = to_ms(ev.extra.get("merged_at") or ev.ts)
    cands = Q.rows(g, """UNWIND $ts AS t MATCH (q:Requirement {ticket: t}) WHERE q.at_ms <= $cut
                         RETURN q.id AS id, q.text AS text, q.at AS at, q.at_ms AS at_ms ORDER BY q.at_ms""",
                   ts=tickets, cut=cutoff)
    implemented = ex.implements({"number": ev.extra["number"], "title": ev.extra["title"], "body": ev.extra["body"]}, cands) if cands else []
    g.query("""UNWIND $rs AS r MATCH (pr:PullRequest {id: $id}), (q:Requirement {id: r})
               MERGE (pr)-[:IMPLEMENTS]->(q)""", {"id": ev.id, "rs": implemented})
    resolved = sorted(r for t in tickets for r in before[t] - _drift_ids(g, t))
    return {"status": "linked" if tickets else "no-ticket", "pr": ev.extra["number"], "tickets": tickets,
            "implements": implemented, "resolved": resolved, "at": from_ms(cutoff)}
