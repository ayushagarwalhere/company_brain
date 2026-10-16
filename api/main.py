"""FastAPI backend for the dashboard.

    uvicorn api.main:app --reload --port 8000     -> http://localhost:8000
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import retro as retro_mod
from api import bus
from api.cache import cached
from api.cache import stats as cache_stats
from api.observability import RateLimiter, observe, render
from agent import tools
from graph import queries as Q
from graph.db import get_graph
from pipeline.events import Event, from_ms

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"  # React app: `cd web && npm run build`
@asynccontextmanager
async def lifespan(_app):
    """Receive events published by other processes (bots, CLI) over FalkorDB's Redis pub/sub."""
    stop = bus.start_listener()
    yield
    stop.set()


app = FastAPI(title="Context Graph Drift Monitor", version="1.0", lifespan=lifespan,
              description="FalkorDB context graph: chat, docs, tickets and PRs linked per requirement; drift detection with graph-path evidence.")


def _cors() -> None:
    """Opt-in CORS (CORS_ORIGINS=comma,separated,origins) for a frontend served from another origin."""
    import os
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])


_cors()


log = logging.getLogger("api")
SLOW_MS = 250.0


@app.middleware("http")
async def org_scope(request: Request, call_next):
    """Multi-tenancy: X-Org header (or ?org=, for EventSource) selects the org's isolated graph."""
    from fastapi.responses import JSONResponse
    from graph.db import set_org
    org = request.headers.get("x-org") or request.query_params.get("org")
    try:
        token = set_org(org)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    try:
        return await call_next(request)
    finally:
        from graph.db import _org
        _org.reset(token)


LIMITED = {"/api/ask", "/api/simulate", "/api/spec"}  # expensive POSTs (LLM / graph writes)
limiter = RateLimiter(rate=int(__import__("os").getenv("RATE_LIMIT_PER_MIN", "30")), per=60.0)


@app.middleware("http")
async def timing(request: Request, call_next):
    """Rate limit for expensive POSTs; Server-Timing header; per-route metrics; slow-request log."""
    path = request.url.path
    if request.method == "POST" and path in LIMITED:
        client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
        if not limiter.allow(client, path):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "rate limit exceeded, try again shortly"}, status_code=429, headers={"Retry-After": "5"})
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    if path != "/api/events":  # the SSE stream is long-lived by design
        response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
        route = request.scope.get("route")
        observe(request.method, getattr(route, "path", "unmatched"), response.status_code, ms)
        if ms > SLOW_MS:
            log.warning("slow request %s %s %.0fms", request.method, path, ms)
    return response


def require_ingest_token(authorization: str | None = Header(default=None), x_ingest_token: str | None = Header(default=None)):
    """Write endpoints (webhooks, reset) need INGEST_TOKEN when it's set. Open when unset (local demo)."""
    import hmac
    import os
    expected = os.getenv("INGEST_TOKEN", "")
    if not expected:
        return
    given = x_ingest_token or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else "")
    if not hmac.compare_digest(given or "", expected):
        raise HTTPException(401, "missing or invalid ingest token")


class AskIn(BaseModel):
    question: str


class SpecIn(BaseModel):
    feature: str


class SimulateIn(BaseModel):
    text: str
    author: str = "maya"
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
    return cached("stats", _stats)


def _stats():
    g = get_graph()
    nodes = Q.rows(g, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC")
    rels = Q.rows(g, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC")
    build = Q.rows(g, "MATCH (b:Build {id: 'latest'}) RETURN b.extractor AS extractor, b.model AS model, b.at AS at")
    nodes = [n for n in nodes if n["label"] != "Build"]
    from config import settings
    from pipeline import llm
    ok, reason = llm.peek()  # never blocks the dashboard on a network call
    return {"nodes": nodes, "relationships": rels, "build": build[0] if build else None,
            "llm": {"model": settings.llm_model, "available": bool(ok), "reason": reason}}


@app.get("/api/features")
def features():
    return cached("features", _features)


def _features():
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
    return cached("drift", _drift, feature)


def _drift(feature: str | None = None):
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
        OPTIONAL MATCH (doc:Document)-[:MENTIONS]->(t)
        RETURN f, t, rs, rc, m, p, pr, doc""", f=feature)
    nodes, edges = {}, set()

    def add(n, kind):
        if n is None:
            return None
        nid = n.properties["id"]
        label = {"Feature": n.properties.get("name"), "Ticket": nid, "PullRequest": f"PR #{n.properties.get('number')}",
                 "Person": n.properties.get("name") or nid, "Document": n.properties.get("title")}.get(kind) \
            or (n.properties.get("text") or nid)[:60]
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
        doc = add(r["doc"], "Document")
        for a, rel, b in ((t, "ABOUT", f), (t, "STATES", rs), (rc, "AMENDS", t), (m, "CHANGES", rc),
                          (p, "POSTED", m), (pr, "REFERENCES", t), (doc, "MENTIONS", t)):
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
        for x in d["stale_docs"]:
            if x["id"] in nodes:
                nodes[x["id"]]["stale"] = True
    return {"nodes": list(nodes.values()), "edges": [{"from": a, "rel": r, "to": b} for a, r, b in edges]}


@app.get("/api/coverage")
def coverage():
    return cached("coverage", _coverage)


def _coverage():
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

@app.get("/api/search")
def search(q: str, limit: int = 12):
    from graph.explore import search as do_search
    return do_search(get_graph(), q, limit)


@app.get("/api/people/{pid}")
def person(pid: str):
    from graph.explore import person as profile
    out = profile(get_graph(), pid)
    if not out:
        raise HTTPException(404, f"unknown person {pid}")
    for d in out["drift_caused"] + out["stale_work"]:
        d["path"] = tools.drift_path(d)
    return out


@app.get("/api/nodes/{nid}/neighbors")
def node_neighbors(nid: str):
    from graph.explore import neighbors
    return neighbors(get_graph(), nid)

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
    bus.publish("drift" if r.get("status") == "drift" else "message", status=r.get("status"), feature=r.get("feature"),
                ticket=r.get("ticket"), author=body.author, text=body.text[:160])
    return r


class DriftActionIn(BaseModel):
    requirement: str
    actor: str = "maya"
    reason: str = "keep the old scope"


@app.post("/api/drift/write-to-ticket")
def drift_write(body: DriftActionIn):
    from pipeline.actions import write_to_ticket
    try:
        out = write_to_ticket(get_graph(), body.requirement, body.actor)
    except ValueError as e:
        raise HTTPException(409, str(e))
    bus.publish("resolved", how="written to ticket", ticket=out["ticket"], requirement=body.requirement, by=body.actor)
    return out


@app.post("/api/drift/dismiss")
def drift_dismiss(body: DriftActionIn):
    from pipeline.actions import dismiss
    try:
        out = dismiss(get_graph(), body.requirement, body.actor, body.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))
    bus.publish("resolved", how="dismissed", requirement=body.requirement, by=body.actor)
    return out


@app.post("/api/demo/reset", dependencies=[Depends(require_ingest_token)])
def demo_reset():
    """Rebuilds the graph from the source data: undoes simulated messages, ticket writes and dismissals."""
    from pipeline import live
    from pipeline.build import mark_build
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    g = get_graph()
    prev = Q.rows(g, "MATCH (b:Build {id: 'latest'}) RETURN b.extractor AS e")
    from pipeline import llm
    extractor = prev[0]["e"] if prev else ("llm" if llm.available() else "heuristic")
    if extractor in ("llm", "deepseek") and not llm.available():
        extractor = "heuristic"  # the key stopped working (no balance, revoked): rebuild without the LLM
    from graph.db import current_graph_name
    ingest(reset=True, graph_name=current_graph_name())
    g = get_graph()
    resolve(g, extractor, log=lambda *_: None)
    mark_build(g, extractor)
    live._last_alert.clear()
    bus.publish("rebuild", extractor=extractor)
    return {"rebuilt_with": extractor}


# ---------------------------------------------------------------- live updates

@app.get("/api/events")
async def events():
    """Server-Sent Events: drift / message / resolved / ticket / pr / rebuild, pushed as they happen (per org)."""
    from graph.db import current_org
    q = bus.subscribe(current_org())
    return StreamingResponse(bus.stream(q), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/orgs")
def orgs():
    from graph.db import current_org, list_orgs
    return {"current": current_org(), "orgs": list_orgs()}


@app.post("/api/orgs/{org}/bootstrap", dependencies=[Depends(require_ingest_token)])
def bootstrap_org(org: str):
    """Creates (or rebuilds) an org's isolated graph from the demo data, so a new tenant can be tried at once."""
    from graph.db import org_graph_name
    from pipeline import llm
    from pipeline.build import mark_build
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    try:
        name = org_graph_name(org)
    except ValueError as e:
        raise HTTPException(400, str(e))
    extractor = "llm" if llm.available() else "heuristic"
    counts = ingest(reset=True, graph_name=name)
    g = get_graph(name)
    resolve(g, extractor, log=lambda *_: None)
    mark_build(g, extractor)
    return {"org": org, "graph": name, "extractor": extractor, "nodes": sum(counts["nodes"].values())}


@app.get("/api/metrics")
def metrics():
    """Prometheus text format: request counts and latency per route, cache, live clients, open drift per org."""
    from fastapi.responses import PlainTextResponse
    from graph.db import current_org
    hits, misses = cache_stats["hits"], cache_stats["misses"]
    extra = {
        "drift_cache_hits_total": hits, "drift_cache_misses_total": misses,
        "drift_event_bus_version": bus.version, "drift_sse_subscribers": len(bus._subscribers),
        f'drift_open_total{{org="{current_org()}"}}': len(_drift()),
    }
    return PlainTextResponse(render(extra), media_type="text/plain; version=0.0.4")


@app.get("/api/cache")
def cache_info():
    return {"version": bus.version, **cache_stats}


@app.get("/api/events/recent")
def recent_events():
    return list(bus.recent)


@app.get("/api/tickets")
def tickets():
    return Q.rows(get_graph(), """MATCH (t:Ticket) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
                                  RETURN t.id AS id, t.title AS title, t.description AS description, t.state AS state,
                                         f.name AS feature ORDER BY id""")


class TicketUpdateIn(BaseModel):
    ticket: str
    description: str
    actor: str = "maya"


@app.post("/api/ingest/ticket", dependencies=[Depends(require_ingest_token)])
def ingest_ticket(body: TicketUpdateIn):
    """Ticket-tracker webhook (Linear/Jira-style): a description changed."""
    from pipeline.webhooks import ticket_updated
    try:
        out = ticket_updated(get_graph(), body.ticket, body.description, body.actor)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if out["status"] == "updated":
        bus.publish("ticket", ticket=body.ticket, by=body.actor, resolved=out["resolved"], still_drifting=out["still_drifting"])
    return out


class DocUpdateIn(BaseModel):
    doc: str
    text: str
    title: str | None = None
    actor: str = "maya"


@app.post("/api/ingest/doc", dependencies=[Depends(require_ingest_token)])
def ingest_doc(body: DocUpdateIn):
    """Docs webhook (Notion/Confluence-style): a page's content changed."""
    from pipeline.webhooks import doc_updated
    try:
        out = doc_updated(get_graph(), body.doc, body.text, body.actor, body.title)
    except ValueError as e:
        raise HTTPException(404, str(e))
    bus.publish("doc", doc=body.doc, by=body.actor, no_longer_stale=out["no_longer_stale"])
    return out


@app.post("/api/ingest/github", dependencies=[Depends(require_ingest_token)])
async def ingest_github(request: Request, x_github_event: str | None = Header(default=None),
                        x_hub_signature_256: str | None = Header(default=None)):
    """GitHub webhook (pull_request events). Verified with GITHUB_WEBHOOK_SECRET when it is set."""
    import os
    from pipeline.webhooks import pr_event, verify_github_signature
    raw = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret and not verify_github_signature(secret, raw, x_hub_signature_256):
        raise HTTPException(401, "bad signature")
    if x_github_event and x_github_event != "pull_request":
        return {"status": "ignored", "event": x_github_event}
    import json
    from starlette.concurrency import run_in_threadpool
    try:
        out = await run_in_threadpool(pr_event, get_graph(), json.loads(raw or b"{}"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    bus.publish("pr", pr=out["pr"], tickets=out["tickets"], resolved=out["resolved"])
    return out


@app.get("/")
def index():
    page = WEB_DIST / "index.html"
    if not page.exists():
        raise HTTPException(503, "Frontend not built: run `npm install && npm run build` in web/")
    # the page must revalidate on every load, or browsers keep running an old build; assets are content-hashed
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")
