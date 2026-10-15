"""Live drift monitor: one new chat message in, maybe one alert out.

Runs the same steps as the batch pipeline, scoped to a single message:
  write message -> resolve feature (hard / thread / semantic) -> classify ->
  if it changes a requirement: add Requirement + SUPERSEDES + Decision ->
  run the drift query for that ticket -> return an alert with the evidence path.

Guards against spam and false positives:
  * only "decision" / "requirement_change" with confidence >= MIN_CONFIDENCE
  * one alert per requirement (Alert node is MERGEd on the requirement id)
  * per-ticket cooldown so a heated thread doesn't post five alerts
  * messages from the bot itself are ignored by the bot adapters
"""
import re
import time

from agent.tools import drift_path
from graph import queries as Q
from graph.db import get_graph
from graph.writer import write_messages
from pipeline.events import Event
from pipeline.extract import CHANGE_KINDS
from pipeline.textsim import TfIdf

MIN_CONFIDENCE = 0.6
TICKET_COOLDOWN_S = 300
_last_alert: dict[str, float] = {}


class HeuristicExtractor:
    """No-API fallback so the monitor can be demoed without a DeepSeek key. Deliberately simple."""
    name = "heuristic"
    DECISION = re.compile(r"\b(decision:|let'?s change|we('ll| will) (now )?(do|send|support|use)|agreed[,:.]|instead of|"
                          r"must (now )?(support|include|be)|from now on|change of plan)", re.I)

    def classify(self, items, features):
        out = {}
        for it in items:
            hit = self.DECISION.search(it["text"])
            out[it["id"]] = {"kind": "decision" if hit else "other", "feature": None, "ticket": None,
                             "requirement": it["text"].strip() if hit else None, "confidence": 0.7 if hit else 0.0}
        return out


def _extractor():
    from config import settings
    if settings.deepseek_api_key:
        from pipeline.extract import DeepSeekExtractor
        return DeepSeekExtractor()
    return HeuristicExtractor()


def _features(g):
    feats = Q.rows(g, """MATCH (f:Feature)<-[:ABOUT]-(t:Ticket)
                         RETURN f.id AS id, f.name AS name, collect({id: t.id, title: t.title, description: t.description,
                                created_ms: t.created_ms}) AS ticket_objs""")
    for f in feats:
        f["tickets"] = [t["id"] for t in f["ticket_objs"]]
    return feats


def process_message(event: Event, g=None, extractor=None) -> dict:
    g = g or get_graph()
    ex = extractor or _extractor()
    write_messages(g, [event])
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
        th = Q.rows(g, """MATCH (m:Message {id: $id})-[:REPLY_TO*1..5]->(p:Message)-[:ABOUT]->(f:Feature)
                          RETURN f.id AS f LIMIT 1""", id=event.id)
        if th:
            feature, via = th[0]["f"], "thread"

    thread = Q.rows(g, """MATCH (m:Message {id: $id})-[:REPLY_TO*1..5]->(p:Message)<-[:POSTED]-(a:Person)
                          RETURN a.id AS author, p.text AS text, p.ts_ms AS ts ORDER BY ts""", id=event.id)
    c = ex.classify([{"id": event.id, "author": event.author, "ts": event.ts, "text": event.text,
                      "thread": [{"author": t["author"], "text": t["text"]} for t in thread]}], feats)[event.id]
    if not feature and c.get("feature") in feat_ids:
        feature, via = c["feature"], "semantic:llm"
    if not feature:
        sim = TfIdf({f["id"]: " ".join(f"{t['title']} {t['description']}" for t in f["ticket_objs"]) for f in feats})
        best, score = sim.best(event.text)
        if best and score >= 0.22:
            feature, via = best, f"semantic:tfidf:{score:.2f}"
    if feature:
        g.query("MATCH (m:Message {id: $m}), (f:Feature {id: $f}) MERGE (m)-[:ABOUT {via: $via}]->(f)",
                {"m": event.id, "f": feature, "via": via})

    result = {"status": "ok", "message": event.id, "feature": feature, "via": via, "classification": c}
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

    rid = f"req:{event.id}"
    g.query("""MATCH (m:Message {id: $m}), (t:Ticket {id: $t}), (f:Feature {id: $f}), (p:Person {id: $p})
               MERGE (q:Requirement {id: $rid})
               SET q.text = $text, q.at_ms = m.ts_ms, q.at = m.ts, q.origin = 'chat', q.ticket = $t, q.confidence = $conf
               MERGE (m)-[:CHANGES {at_ms: m.ts_ms}]->(q)
               MERGE (q)-[:AMENDS]->(t)
               MERGE (q)-[:ABOUT]->(f)
               WITH m, q, p
               MERGE (d:Decision {id: 'dec:' + m.id})
               SET d.text = q.text, d.at_ms = q.at_ms, d.at = q.at
               MERGE (p)-[:MADE]->(d)
               MERGE (d)-[:RECORDED_IN]->(m)
               MERGE (d)-[:CHANGES]->(q)""",
            {"m": event.id, "t": ticket, "f": feature, "p": event.author, "rid": rid,
             "text": c["requirement"], "conf": c.get("confidence")})
    # the new requirement supersedes whatever was newest for this ticket
    g.query("""MATCH (q:Requirement {id: $rid})
               MATCH (old:Requirement {ticket: $t}) WHERE old.id <> q.id AND old.at_ms <= q.at_ms
                 AND NOT (old)<-[:SUPERSEDES]-(:Requirement)
               MERGE (q)-[:SUPERSEDES]->(old)""", {"rid": rid, "t": ticket})

    found = [d for d in Q.drift(g, ticket=ticket) if d["requirement"] == rid]
    if not found:
        return {**result, "status": "change-reflected", "ticket": ticket}
    d = found[0]
    now = time.time()
    if now - _last_alert.get(ticket, 0) < TICKET_COOLDOWN_S:
        return {**result, "status": "cooldown", "ticket": ticket}
    existing = Q.rows(g, "MATCH (a:Alert {id: $id}) RETURN a.id AS id", id=f"alert:{rid}")
    if existing:
        return {**result, "status": "already-alerted", "ticket": ticket}
    _last_alert[ticket] = now
    g.query("""MATCH (q:Requirement {id: $rid})
               MERGE (a:Alert {id: $aid}) SET a.at_ms = $at, a.status = 'open'
               MERGE (a)-[:FLAGS]->(q)""", {"rid": rid, "aid": f"alert:{rid}", "at": int(now * 1000)})
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
        lines.append("PRs on this ticket implement the old version: " + ", ".join(f"#{p['pr']} {p['title']}" for p in stale))
    lines.append(f"Graph path: `Message -CHANGES-> Requirement -AMENDS-> Ticket {d['ticket']} -ABOUT-> Feature {d['feature']}`"
                 + (f" ; `PR #{stale[0]['pr']} -IMPLEMENTS-> older requirement`" if stale else ""))
    lines.append(f"Suggested fix: update {d['ticket']} or confirm the old scope.")
    return "\n".join(lines)
