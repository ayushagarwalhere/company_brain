"""Live drift monitor: one new chat message in, maybe one alert out.

Runs the same steps as the batch pipeline, scoped to a single message:
  write message -> (a project status change? apply it and stop: see pipeline/orgchange.py) ->
  resolve feature (hard / thread / semantic) -> classify ->
  if it changes a requirement: add Requirement + SUPERSEDES + Decision ->
  run the drift query for that ticket -> return an alert with the evidence path.

Guards against spam and false positives:
  * only "decision" / "requirement_change" with confidence >= MIN_CONFIDENCE
  * only from the amended ticket's creator or assignee (decision rights, see benchmark/noise.py)
  * one alert per requirement (Alert node is MERGEd on the requirement id)
  * per-ticket cooldown so a heated thread doesn't post five alerts
  * messages from the bot itself are ignored by the bot adapters
"""

import logging
import time

from agent.tools import drift_path
from config import MIN_CONFIDENCE, MSG_SIM_THRESHOLD  # noqa: E402 - one threshold for batch and live
from graph import queries as Q
from graph.db import get_graph
from graph.writer import link_doc_references, write_messages
from pipeline.events import Event
from pipeline.extract import CHANGE_KINDS, HeuristicExtractor  # noqa: F401 - re-exported for tests
from pipeline.resolve import has_decision_rights
from pipeline.textsim import TfIdf

TICKET_COOLDOWN_S = 300
log = logging.getLogger(__name__)
_last_alert: dict[tuple[str, str], float] = {}  # (org, ticket) -> last alert time


def _extractor():
    from pipeline import llm

    if llm.available():
        from pipeline.extract import LLMExtractor

        return LLMExtractor()
    return HeuristicExtractor()


def _features(g):
    feats = Q.rows(
        g,
        """MATCH (f:Feature)<-[:ABOUT]-(t:Ticket)
                         RETURN f.id AS id, f.name AS name, collect({id: t.id, title: t.title, description: t.description,
                                created_ms: t.created_ms}) AS ticket_objs""",
    )
    for f in feats:
        f["tickets"] = [t["id"] for t in f["ticket_objs"]]
    return feats


def process_message(event: Event, g=None, extractor=None) -> dict:
    g = g or get_graph()
    ex = extractor or _extractor()
    write_messages(g, [event])
    link_doc_references(g, [event.id])
    from pipeline.orgchange import apply_project_status

    org_change = apply_project_status(g, event)
    if org_change:  # a decision about a whole project, not a ticket's requirement: no drift check
        return {"status": "project-status", "message": event.id, "change": org_change}
    feats = _features(g)
    if not feats:
        return {"status": "no-features"}
    feat_ids = {f["id"] for f in feats}

    # --- resolve feature: hard -> thread -> semantic
    via, feature = None, None
    hard = Q.rows(g, "MATCH (:Message {id: $id})-[:MENTIONS]->(t:Ticket)-[:ABOUT]->(f:Feature) RETURN f.id AS f LIMIT 1", id=event.id)
    if hard:
        feature, via = hard[0]["f"], "hard"
    if not feature and event.thread_of:
        th = Q.rows(
            g,
            """MATCH (m:Message {id: $id})-[:REPLY_TO*1..5]->(p:Message)-[:ABOUT]->(f:Feature)
                          RETURN f.id AS f LIMIT 1""",
            id=event.id,
        )
        if th:
            feature, via = th[0]["f"], "thread"

    thread = Q.rows(
        g,
        """MATCH (m:Message {id: $id})-[:REPLY_TO*1..5]->(p:Message)<-[:POSTED]-(a:Person)
                          RETURN a.id AS author, p.text AS text, p.ts_ms AS ts ORDER BY ts""",
        id=event.id,
    )
    c = ex.classify(
        [{"id": event.id, "author": event.author, "ts": event.ts, "text": event.text, "thread": [{"author": t["author"], "text": t["text"]} for t in thread]}],
        feats,
    )[event.id]
    if not feature and c.get("feature") in feat_ids:
        feature, via = c["feature"], "semantic:llm"
    if not feature:
        sim = TfIdf({f["id"]: " ".join(f"{t['title']} {t['description']}" for t in f["ticket_objs"]) for f in feats})
        best, score = sim.best(event.text)
        if best and score >= MSG_SIM_THRESHOLD:
            feature, via = best, f"semantic:tfidf:{score:.2f}"
    if feature:
        g.query("MATCH (m:Message {id: $m}), (f:Feature {id: $f}) MERGE (m)-[:ABOUT {via: $via}]->(f)", {"m": event.id, "f": feature, "via": via})

    result = {"status": "ok", "message": event.id, "feature": feature, "via": via, "classification": c}
    if c.get("kind") == "error":  # the LLM call failed: report it, don't pass it off as "not a decision"
        log.warning("live classification failed for %s: %s", event.id, c.get("error"))
        return {**result, "status": "llm-error"}
    if c.get("kind") not in CHANGE_KINDS or not c.get("requirement") or not feature:
        return result
    if (c.get("confidence") or 0) < MIN_CONFIDENCE:
        return {**result, "status": "low-confidence"}

    # --- which ticket does it amend?
    f = next(x for x in feats if x["id"] == feature)
    ticket = c.get("ticket") if c.get("ticket") in f["tickets"] else None
    if not ticket:
        mentioned = Q.rows(g, "MATCH (:Message {id: $id})-[:MENTIONS]->(t:Ticket) RETURN t.id AS t", id=event.id)
        ticket = next((m["t"] for m in mentioned if m["t"] in f["tickets"]), None)
    if not ticket:
        sim = TfIdf({t["id"]: f"{t['title']} {t['description']}" for t in f["ticket_objs"]})
        ticket, _ = sim.best(f"{c['requirement']} {event.text}")
    owners = Q.rows(
        g,
        """MATCH (t:Ticket {id: $t}) OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t)
                         OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person) RETURN c.id AS creator, p.id AS assignee""",
        t=ticket,
    )
    if not owners or not has_decision_rights(event.author, owners[0]):
        return {**result, "status": "no-decision-rights", "ticket": ticket}

    rid = f"req:{event.id}"
    g.query(
        """MATCH (m:Message {id: $m}), (t:Ticket {id: $t}), (f:Feature {id: $f}), (p:Person {id: $p})
               MERGE (q:Requirement {id: $rid})
               SET q.text = $text, q.at_ms = m.ts_ms, q.at = m.ts, q.origin = 'chat', q.ticket = $t, q.confidence = $conf
               MERGE (m)-[:CHANGES {at_ms: m.ts_ms}]->(q)
               MERGE (q)-[:AMENDS]->(t)
               MERGE (q)-[:ABOUT]->(f)
               WITH m, q, p
               MERGE (d:Decision {id: 'dec:' + m.id})
               SET d.text = q.text, d.at_ms = q.at_ms, d.at = q.at, d.origin = 'extractor'
               MERGE (p)-[:MADE]->(d)
               MERGE (d)-[:RECORDED_IN]->(m)
               MERGE (d)-[:CHANGES]->(q)""",
        {"m": event.id, "t": ticket, "f": feature, "p": event.author, "rid": rid, "text": c["requirement"], "conf": c.get("confidence")},
    )
    # rebuild this ticket's SUPERSEDES chain with the same rules as the batch build
    from pipeline.webhooks import recompute_supersession

    recompute_supersession(g, ticket, ex)

    found = [d for d in Q.drift(g, ticket=ticket) if d["requirement"] == rid]
    if not found:
        return {**result, "status": "change-reflected", "ticket": ticket}
    d = found[0]
    now = time.time()
    from graph.db import current_org

    key = (current_org(), ticket)
    if now - _last_alert.get(key, 0) < TICKET_COOLDOWN_S:
        return {**result, "status": "cooldown", "ticket": ticket}
    existing = Q.rows(g, "MATCH (a:Alert {id: $id}) RETURN a.id AS id", id=f"alert:{rid}")
    if existing:
        return {**result, "status": "already-alerted", "ticket": ticket}
    _last_alert[key] = now
    g.query(
        """MATCH (q:Requirement {id: $rid})
               MERGE (a:Alert {id: $aid}) SET a.at_ms = $at, a.status = 'open'
               MERGE (a)-[:FLAGS]->(q)""",
        {"rid": rid, "aid": f"alert:{rid}", "at": int(now * 1000)},
    )
    return {**result, "status": "drift", "ticket": ticket, "drift": d, "path": drift_path(d), "alert": format_alert(d)}


def format_alert(d: dict) -> str:
    stale = [p for p in d["stale_prs"] if p["pr"] is not None]
    lines = [
        f":warning: *Requirement drift on {d['feature_name']}*",
        f"This message changes what *{d['ticket']}* asks for:",
        f"> {d['requirement_text']}",
        f"But {d['ticket']} still says:",
        f"> {d['ticket_text']}",
    ]
    if stale:
        lines.append(
            "PRs that shipped the old version: "
            + ", ".join(f"#{p['pr']} {p['title']}" + (" (after the decision)" if p["status"] == "old_after" else "") for p in stale)
        )
    if d.get("unmatched_prs"):
        lines.append("Unmatched, may implement the new scope: " + ", ".join(f"#{p['pr']} {p['title']}" for p in d["unmatched_prs"]))
    lines.append(
        f"Graph path: `Message -CHANGES-> Requirement -AMENDS-> Ticket {d['ticket']} -ABOUT-> Feature {d['feature']}`"
        + (f" ; `PR #{stale[0]['pr']} -IMPLEMENTS-> older requirement`" if stale else "")
    )
    lines.append(f"Suggested fix: update {d['ticket']} or confirm the old scope.")
    return "\n".join(lines)


# ---------------------------------------------------------------- edits and deletions (keeping the graph current)


def mark_dirty(g) -> None:
    """Something changed that the next full resolve must take into account (an edited or deleted message): the team
    sync (pipeline/teamsync.py) re-derives features, requirements and drift when it sees this flag."""
    g.query("MERGE (s:SyncState {id: 'resolve'}) SET s.dirty = true")


def edit_message(event: Event, g=None, extractor=None) -> dict:
    """A message was edited: its new text replaces the old one and is checked like a new message (the edit may be the
    decision); whatever the old text implied is re-derived at the next resolve."""
    g = g or get_graph()
    out = process_message(event, g, extractor)
    mark_dirty(g)
    return out


def delete_message(message_id: str, g=None) -> bool:
    """A message was deleted: it leaves the graph, and with the next resolve so does any requirement it created."""
    g = g or get_graph()
    gone = g.query("MATCH (m:Message {id: $id}) DETACH DELETE m RETURN count(*)", {"id": message_id}).result_set
    mark_dirty(g)
    return bool(gone and gone[0][0])
