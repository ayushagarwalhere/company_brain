"""FastAPI backend for the dashboard.

    uvicorn api.main:app --reload --port 8000     -> http://localhost:8000
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import retro as retro_mod
from agent import tools
from graph import queries as Q
from graph.db import get_graph
from pipeline.events import Event, from_ms

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app = FastAPI(title="Context Graph Drift Monitor")


class AskIn(BaseModel):
    question: str


class SpecIn(BaseModel):
    feature: str


class SimulateIn(BaseModel):
    text: str
    author: str = "zara"
    platform: str = "slack"
    channel: str = "engineering"
    reply_to: str | None = None


@app.get("/api/health")
def health():
    g = get_graph()
    n = Q.rows(g, "MATCH (n) RETURN count(n) AS n")[0]["n"]
    return {"ok": True, "nodes": n}


@app.get("/api/stats")
def stats():
    g = get_graph()
    nodes = Q.rows(g, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC")
    rels = Q.rows(g, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC")
    build = Q.rows(g, "MATCH (b:Build {id: 'latest'}) RETURN b.extractor AS extractor, b.at AS at")
    nodes = [n for n in nodes if n["label"] != "Build"]
    return {"nodes": nodes, "relationships": rels, "build": build[0] if build else None}


@app.get("/api/features")
def features():
    g = get_graph()
    rows = Q.rows(g, """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                        WITH f, collect(t.id) AS tickets
                        OPTIONAL MATCH (pr:PullRequest)-[:ABOUT]->(f)
                        WITH f, tickets, collect(pr.number) AS prs
                        OPTIONAL MATCH (m:Message)-[:ABOUT]->(f)
                        RETURN f.id AS id, f.name AS name, tickets, prs, count(m) AS messages ORDER BY id""")
    drifted = {d["feature"] for d in Q.drift(g)}
    for r in rows:
        r["drift"] = r["id"] in drifted
    return rows


@app.get("/api/drift")
def drift(feature: str | None = None):
    rows = Q.drift(get_graph(), feature=feature)
    for d in rows:
        d["path"] = tools.drift_path(d)
        d["stale_prs"] = [p for p in d["stale_prs"] if p["pr"] is not None]
    return rows


@app.get("/api/alerts")
def alerts():
    rows = Q.rows(get_graph(), """MATCH (a:Alert)-[:FLAGS]->(r:Requirement)<-[:CHANGES]-(m:Message)
                                  MATCH (r)-[:AMENDS]->(t:Ticket)
                                  RETURN a.id AS id, a.at_ms AS at_ms, r.text AS requirement, t.id AS ticket,
                                         m.text AS message, m.source AS source, m.channel AS channel
                                  ORDER BY at_ms DESC LIMIT 20""")
    for r in rows:
        r["at"] = from_ms(r.pop("at_ms"))
    return rows


@app.get("/api/sprints")
def sprints():
    return Q.rows(get_graph(), "MATCH (s:Sprint) RETURN s.id AS id, s.name AS name, s.start AS start, s.end AS end ORDER BY id")


@app.get("/api/retro/{sprint}")
def retro(sprint: str):
    try:
        r = retro_mod.retro(sprint)
    except ValueError as e:
        raise HTTPException(404, str(e))
    for d in r["diverged"]:
        d["stale_prs"] = [p for p in d["stale_prs"] if p["pr"] is not None]
    return {**r, "markdown": retro_mod.to_markdown(r)}


@app.get("/api/features/{feature}/history")
def history(feature: str):
    return tools.decision_history(feature)


@app.get("/api/features/{feature}/experts")
def experts(feature: str):
    return tools.who_knows(feature)["rows"]


@app.get("/api/features/{feature}/graph")
def feature_graph(feature: str):
    """Subgraph around a feature for the visualisation (no noise messages)."""
    g = get_graph()
    rows = Q.rows(g, """MATCH (f:Feature {id: $f})
        OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
        OPTIONAL MATCH (t)-[:STATES]->(rs:Requirement)
        OPTIONAL MATCH (rc:Requirement)-[:AMENDS]->(t)
        OPTIONAL MATCH (m:Message)-[:CHANGES]->(rc)
        OPTIONAL MATCH (p:Person)-[:POSTED]->(m)
        OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
        RETURN f, t, rs, rc, m, p, pr""", f=feature)
    nodes, edges = {}, set()

    def add(n, kind):
        if n is None:
            return None
        nid = n.properties["id"]
        label = {"Feature": n.properties.get("name"), "Ticket": nid, "PullRequest": f"PR #{n.properties.get('number')}",
                 "Person": n.properties.get("name") or nid}.get(kind) or (n.properties.get("text") or nid)[:60]
        nodes[nid] = {"id": nid, "label": label, "type": kind,
                      "text": n.properties.get("text") or n.properties.get("description") or n.properties.get("title")}
        return nid

    for r in rows:
        f = add(r["f"], "Feature")
        t = add(r["t"], "Ticket")
        rs = add(r["rs"], "Requirement")
        rc = add(r["rc"], "Requirement")
        m = add(r["m"], "Message")
        p = add(r["p"], "Person")
        pr = add(r["pr"], "PullRequest")
        for a, rel, b in ((t, "ABOUT", f), (t, "STATES", rs), (rc, "AMENDS", t), (m, "CHANGES", rc),
                          (p, "POSTED", m), (pr, "REFERENCES", t)):
            if a and b:
                edges.add((a, rel, b))
    for e in Q.rows(g, """MATCH (a:Requirement)-[x:SUPERSEDES|IMPLEMENTS]->(b:Requirement) WHERE a.id IN $ids
                          RETURN a.id AS a, type(x) AS rel, b.id AS b""", ids=list(nodes)):
        edges.add((e["a"], e["rel"], e["b"]))
    for e in Q.rows(g, """MATCH (a:PullRequest)-[:IMPLEMENTS]->(b:Requirement) WHERE a.id IN $ids
                          RETURN a.id AS a, b.id AS b""", ids=list(nodes)):
        edges.add((e["a"], "IMPLEMENTS", e["b"]))
    for d in Q.drift(g, feature=feature):
        if d["requirement"] in nodes:
            nodes[d["requirement"]]["drift"] = True
    return {"nodes": list(nodes.values()), "edges": [{"from": a, "rel": r, "to": b} for a, r, b in edges]}


@app.get("/api/coverage")
def coverage():
    """Holes in the company's knowledge: unlinked work, undiscussed tickets, concentrated expertise."""
    g = get_graph()
    return {
        "orphan_prs": Q.rows(g, Q.ORPHAN_PRS),
        "done_without_pr": Q.rows(g, Q.DONE_WITHOUT_PR),
        "undiscussed_tickets": Q.rows(g, Q.UNDISCUSSED_TICKETS),
        "knowledge_risk": Q.rows(g, Q.KNOWLEDGE_RISK),
    }


@app.get("/api/features/{feature}/timeline")
def timeline(feature: str):
    g = get_graph()
    events = Q.rows(g, Q.FEATURE_EVENTS, feature=feature)
    drifted = {d["requirement"] for d in Q.drift(g, feature=feature)}
    superseded = {r["id"] for r in Q.rows(g, "MATCH (:Requirement)-[:SUPERSEDES]->(r:Requirement) RETURN r.id AS id")}
    for e in events:
        e["iso"] = from_ms(e["at"])
        e["drift"] = e["id"] in drifted
        e["superseded"] = e["id"] in superseded
    return events

@app.get("/api/connect")
def connect(a: str, b: str):
    return tools.how_connected(a, b)

@app.post("/api/ask")
def ask(body: AskIn):
    from agent.agent import ask as agent_ask
    try:
        return agent_ask(body.question)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/spec")
def spec(body: SpecIn):
    from agent.spec import generate_spec
    try:
        out = generate_spec(body.feature)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {k: out[k] for k in ("feature", "markdown", "engine")}


@app.post("/api/simulate")
def simulate(body: SimulateIn):
    """Inject a chat message as if it arrived from Slack/Discord, and run the live drift monitor."""
    from pipeline.live import process_message
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = Event(source=body.platform, kind="message", id=f"sim:{uuid.uuid4().hex[:10]}", author=body.author,
               ts=now, text=body.text, url="", channel=body.channel, thread_of=body.reply_to)
    r = process_message(ev)
    r.pop("drift", None)
    return r


class DriftActionIn(BaseModel):
    requirement: str
    actor: str = "maya"
    reason: str = "keep the old scope"


@app.post("/api/drift/write-to-ticket")
def drift_write(body: DriftActionIn):
    from pipeline.actions import write_to_ticket
    try:
        return write_to_ticket(get_graph(), body.requirement, body.actor)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/drift/dismiss")
def drift_dismiss(body: DriftActionIn):
    from pipeline.actions import dismiss
    try:
        return dismiss(get_graph(), body.requirement, body.actor, body.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/demo/reset")
def demo_reset():
    """Rebuilds the graph from the source data: undoes simulated messages, ticket writes and dismissals."""
    from config import settings
    from pipeline import live
    from pipeline.build import mark_build
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    g = get_graph()
    prev = Q.rows(g, "MATCH (b:Build {id: 'latest'}) RETURN b.extractor AS e")
    extractor = prev[0]["e"] if prev else ("deepseek" if settings.deepseek_api_key else "heuristic")
    ingest(reset=True)
    g = get_graph()
    resolve(g, extractor, log=lambda *_: None)
    mark_build(g, extractor)
    live._last_alert.clear()
    return {"rebuilt_with": extractor}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
