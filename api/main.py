"""FastAPI backend for the dashboard.

uvicorn api.main:app --reload --port 8000     -> http://localhost:8000
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import retro as retro_mod
from agent import tools
from api import bus
from api.cache import cached
from api.cache import stats as cache_stats
from api.observability import RateLimiter, observe, render
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


app = FastAPI(
    title="Context Graph Drift Monitor",
    version="1.0",
    lifespan=lifespan,
    description="FalkorDB context graph: chat, docs, tickets and PRs linked per requirement; drift detection with graph-path evidence.",
)


def _cors() -> None:
    """Opt-in CORS (CORS_ORIGINS=comma,separated,origins) for a frontend served from another origin."""
    import os

    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])


_cors()

from api.integrations import router as _integrations  # noqa: E402 - connect Slack and Discord from the website

app.include_router(_integrations)


log = logging.getLogger("api")
SLOW_MS = 250.0


@app.middleware("http")
async def access_scope(request: Request, call_next):
    """Entity-level access control (pipeline/access.py). The viewer is the X-User header (person id; behind SSO this
    is the signed-in user), else anonymous. Every JSON response is redacted for that viewer: anything that mentions a
    document they may not see is removed, so no endpoint can leak it, including ones added later."""
    import json as _json

    from fastapi.responses import Response

    from pipeline.access import hidden, redact, reset_viewer, set_viewer

    token = set_viewer(request.headers.get("x-user") or request.query_params.get("as"))
    try:
        response = await call_next(request)
        if not request.url.path.startswith("/api/") or request.url.path == "/api/events" or "json" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        from pipeline.access import current_viewer

        h = hidden(get_graph(), current_viewer())
        if h["ids"]:
            body = _json.dumps(redact(_json.loads(body), h), ensure_ascii=False).encode()
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(body, status_code=response.status_code, headers=headers, media_type="application/json")
    finally:
        reset_viewer(token)


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


# expensive or state-changing POSTs (LLM calls / graph writes)
LIMITED = {"/api/ask", "/api/simulate", "/api/spec", "/api/drift/write-to-ticket", "/api/drift/dismiss", "/api/drift/apply", "/api/drift/keep"}
limiter = RateLimiter(rate=int(__import__("os").getenv("RATE_LIMIT_PER_MIN", "30")), per=60.0)


@app.middleware("http")
async def timing(request: Request, call_next):
    """Rate limit for expensive POSTs; Server-Timing header; per-route metrics; slow-request log."""
    path = request.url.path
    if request.method == "POST" and path in LIMITED:
        # X-Forwarded-For is client-controlled; only trust it behind a proxy that sets it (TRUST_PROXY=1)
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip() if __import__("os").getenv("TRUST_PROXY") else ""
        client = fwd or (request.client.host if request.client else "?")
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
    """Every endpoint that changes the graph (webhooks, reset, simulate, write-to-ticket, dismiss) needs INGEST_TOKEN
    when it's set. Open when unset (local demo). The dashboard sends the token from a ?token= link."""
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
    from pipeline.access import current_viewer

    return cached("stats", _stats, current_viewer())  # per viewer: what they may not see isn't counted either


def _stats(viewer: str | None = None):
    from pipeline.access import hidden

    g = get_graph()
    nodes = Q.rows(g, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC")
    rels = Q.rows(g, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC")
    gone = hidden(g, viewer)["ids"]
    if gone:  # leave out the documents this viewer may not see, their chunks, and every edge touching them
        nd = Q.rows(
            g, "MATCH (d:Document) WHERE d.id IN $ids OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) RETURN count(DISTINCT d) AS d, count(c) AS c", ids=gone
        )[0]
        less = {"Document": nd["d"], "Chunk": nd["c"]}
        less_rels = {r["type"]: r["n"] for r in Q.rows(g, "MATCH (d:Document)-[r]-() WHERE d.id IN $ids RETURN type(r) AS type, count(r) AS n", ids=gone)}
        nodes = [{**n, "n": n["n"] - less.get(n["label"], 0)} for n in nodes if n["n"] > less.get(n["label"], 0)]
        rels = [{**r, "n": r["n"] - less_rels.get(r["type"], 0)} for r in rels if r["n"] > less_rels.get(r["type"], 0)]
    build = Q.rows(
        g,
        "MATCH (b:Build {id: 'latest'}) RETURN b.extractor AS extractor, b.model AS model, b.at AS at, b.reference_date AS reference_date, "
        "b.llm_errors AS llm_errors, b.classified AS classified",
    )
    nodes = [n for n in nodes if n["label"] != "Build"]
    from config import settings
    from pipeline import llm

    ok, reason = llm.peek()  # never blocks the dashboard on a network call
    return {
        "nodes": nodes,
        "relationships": rels,
        "build": build[0] if build else None,
        "llm": {"model": settings.llm_model, "available": bool(ok), "reason": reason},
    }


@app.get("/api/features")
def features():
    return cached("features", _features)


def _features():
    g = get_graph()
    rows = Q.rows(
        g,
        """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                        WITH f, collect(t.id) AS tickets
                        OPTIONAL MATCH (pr:PullRequest)-[:ABOUT]->(f)
                        WITH f, tickets, collect(pr.number) AS prs
                        OPTIONAL MATCH (m:Message)-[:ABOUT]->(f)
                        RETURN f.id AS id, f.name AS name, tickets, prs, count(m) AS messages ORDER BY id""",
    )
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
    rows = Q.rows(
        get_graph(),
        """MATCH (a:Alert)-[:FLAGS]->(r:Requirement)<-[:CHANGES]-(m:Message)
                                  MATCH (r)-[:AMENDS]->(t:Ticket)
                                  RETURN a.id AS id, a.at_ms AS at_ms, r.text AS requirement, t.id AS ticket,
                                         m.text AS message, m.source AS source, m.channel AS channel
                                  ORDER BY at_ms DESC LIMIT 20""",
    )
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
        raise HTTPException(404, str(e)) from e
    for d in r["diverged"]:
        d["stale_prs"] = [p for p in d["stale_prs"] if p["pr"] is not None]
    return {**r, "markdown": retro_mod.to_markdown(r)}


@app.get("/api/features/{feature}/history")
def history(feature: str):
    return tools.decision_history(feature)


@app.get("/api/features/{feature}/experts")
def experts(feature: str):
    return tools.who_knows(feature)["rows"]


@app.get("/api/projects")
def projects_list():
    from pipeline.impact import projects

    return projects(get_graph())


@app.get("/api/impact")
def impact(target: str, days: int = 14):
    """If `target` (project, feature or ticket) slips `days` days: downstream projects, client deliverables, teams,
    with the evidence paths and a layered graph for the view (pipeline/impact.py)."""
    from pipeline.impact import impact_of_delay

    out = impact_of_delay(get_graph(), target, max(0, min(days, 365)))
    if not out.get("target"):
        raise HTTPException(404, out.get("error") or "unknown target")
    return out


@app.get("/api/features/{feature}/map")
def feature_map(feature: str):
    """Everything around a feature, in columns: teams, people, specs (who introduced each version), tickets and docs,
    the work on them, projects, deliverables, clients."""
    from pipeline.impact import feature_map as fmap

    return fmap(get_graph(), feature)


@app.get("/api/features/{feature}/graph")
def feature_graph(feature: str):
    """Subgraph around a feature for the visualisation (no noise messages)."""
    g = get_graph()
    rows = Q.rows(
        g,
        """MATCH (f:Feature {id: $f})
        OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
        OPTIONAL MATCH (t)-[:STATES]->(rs:Requirement)
        OPTIONAL MATCH (rc:Requirement)-[:AMENDS]->(t)
        OPTIONAL MATCH (m:Message)-[:CHANGES]->(rc)
        OPTIONAL MATCH (p:Person)-[:POSTED]->(m)
        OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
        OPTIONAL MATCH (doc:Document)-[:MENTIONS]->(t)
        RETURN f, t, rs, rc, m, p, pr, doc""",
        f=feature,
    )
    nodes, edges = {}, set()

    def add(n, kind):
        if n is None:
            return None
        nid = n.properties["id"]
        label = {
            "Feature": n.properties.get("name"),
            "Ticket": nid,
            "PullRequest": f"PR #{n.properties.get('number')}",
            "Person": n.properties.get("name") or nid,
            "Document": n.properties.get("title"),
        }.get(kind) or (n.properties.get("text") or nid)[:60]
        nodes[nid] = {"id": nid, "label": label, "type": kind, "text": n.properties.get("text") or n.properties.get("description") or n.properties.get("title")}
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
        for a, rel, b in (
            (t, "ABOUT", f),
            (t, "STATES", rs),
            (rc, "AMENDS", t),
            (m, "CHANGES", rc),
            (p, "POSTED", m),
            (pr, "REFERENCES", t),
            (doc, "MENTIONS", t),
        ):
            if a and b:
                edges.add((a, rel, b))
    for e in Q.rows(
        g,
        """MATCH (a:Requirement)-[x:SUPERSEDES|IMPLEMENTS]->(b:Requirement) WHERE a.id IN $ids
                          RETURN a.id AS a, type(x) AS rel, b.id AS b""",
        ids=list(nodes),
    ):
        edges.add((e["a"], e["rel"], e["b"]))
    for e in Q.rows(
        g,
        """MATCH (a:PullRequest)-[:IMPLEMENTS]->(b:Requirement) WHERE a.id IN $ids
                          RETURN a.id AS a, b.id AS b""",
        ids=list(nodes),
    ):
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
        "unverified_changes": Q.rows(g, Q.UNVERIFIED_CHANGES),
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


_PATH_NODE = __import__("re").compile(r"\((\w+) ([^)@]+?)(?:\s@[^)]*)?\)")


def answer_sources(g, paths: list[str]) -> list[dict]:
    """Where an answer's evidence lives: the systems behind the nodes on its graph paths (Slack or Discord channel
    for messages and the decisions/requirements they created, GitHub for PRs, the tracker for tickets, docs)."""
    found: list[tuple[str, str]] = []
    for p in paths:
        for typ, nid in _PATH_NODE.findall(p):
            if (typ, nid.strip()) not in found:
                found.append((typ, nid.strip()))
    msg_ids = {
        nid.removeprefix("dec:").removeprefix("req:")
        for typ, nid in found
        if typ == "Message" or (typ == "Decision" and nid.startswith("dec:")) or (typ == "Requirement" and nid.startswith("req:m_"))
    }
    where = (
        {r["id"]: r for r in Q.rows(g, "MATCH (m:Message) WHERE m.id IN $ids RETURN m.id AS id, m.source AS source, m.channel AS channel", ids=sorted(msg_ids))}
        if msg_ids
        else {}
    )
    out: dict[str, dict] = {}
    for typ, nid in found:
        mid = nid.removeprefix("dec:").removeprefix("req:")
        if mid in where:
            m = where[mid]
            key, label = f"{m['source']}#{m['channel']}", f"{(m['source'] or 'chat').capitalize()} #{m['channel']}"
        elif typ == "PullRequest":
            key, label = "github", "GitHub"
        elif typ == "Ticket" or (typ == "Requirement" and ":v" in nid):
            key, label = "tracker", "Tracker"
        elif typ == "Document":
            key, label = "docs", "Docs"
        else:
            continue
        src = out.setdefault(key, {"system": key.split("#")[0], "label": label, "refs": []})
        ref = nid.split(":")[1] if typ == "Requirement" and ":v" in nid else nid
        if ref not in src["refs"]:
            src["refs"].append(ref)
    return list(out.values())


@app.post("/api/ask")
def ask(body: AskIn):
    from agent.agent import ask as agent_ask

    try:
        out = agent_ask(body.question)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    try:
        out["sources"] = answer_sources(get_graph(), out.get("paths") or [])
    except Exception:  # noqa: BLE001 - badges are a nicety; never fail the answer over them
        log.warning("could not resolve answer sources", exc_info=True)
        out["sources"] = []
    return out


@app.post("/api/spec")
def spec(body: SpecIn):
    from agent.spec import generate_spec

    try:
        out = generate_spec(body.feature)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {k: out[k] for k in ("feature", "markdown", "engine")}


@app.post("/api/simulate", dependencies=[Depends(require_ingest_token)])
def simulate(body: SimulateIn):
    """Inject a chat message as if it arrived from Slack/Discord, and run the live drift monitor."""
    from pipeline.live import process_message

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = Event(
        source=body.platform,
        kind="message",
        id=f"sim:{uuid.uuid4().hex[:10]}",
        author=body.author,
        ts=now,
        text=body.text,
        url="",
        channel=body.channel,
        thread_of=body.reply_to,
    )
    r = process_message(ev)
    r.pop("drift", None)
    bus.publish(
        "drift" if r.get("status") == "drift" else "message",
        status=r.get("status"),
        feature=r.get("feature"),
        ticket=r.get("ticket"),
        author=body.author,
        text=body.text[:160],
    )
    return r


class DriftActionIn(BaseModel):
    requirement: str
    actor: str = "maya"
    reason: str = "keep the old scope"


@app.post("/api/drift/write-to-ticket", dependencies=[Depends(require_ingest_token)])
def drift_write(body: DriftActionIn):
    from pipeline.actions import write_to_ticket

    try:
        out = write_to_ticket(get_graph(), body.requirement, body.actor)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    bus.publish("resolved", how="written to ticket", ticket=out["ticket"], requirement=body.requirement, by=body.actor)
    return out


@app.post("/api/drift/dismiss", dependencies=[Depends(require_ingest_token)])
def drift_dismiss(body: DriftActionIn):
    from pipeline.actions import dismiss

    try:
        out = dismiss(get_graph(), body.requirement, body.actor, body.reason)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    bus.publish("resolved", how="dismissed", requirement=body.requirement, by=body.actor)
    return out


class PlanIn(BaseModel):
    requirement: str


@app.post("/api/drift/plan")
def drift_plan(body: PlanIn):
    """What has to change to close this drift, and who owns each part (read-only)."""
    from pipeline.work import plan

    try:
        p = plan(get_graph(), body.requirement)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {k: p[k] for k in ("owners", "decided_by", "items", "tell", "can_apply")}


@app.post("/api/drift/apply", dependencies=[Depends(require_ingest_token)])
def drift_apply(body: DriftActionIn):
    """An owner approves the plan: the decision goes into the ticket, follow-ups are assigned."""
    from pipeline.work import NotAllowed, apply

    try:
        out = apply(get_graph(), body.requirement, body.actor)
    except NotAllowed as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    bus.publish("resolved", how="plan applied", ticket=out["ticket"], requirement=body.requirement, by=body.actor, tasks=len(out["tasks"]))
    return out


@app.post("/api/drift/keep", dependencies=[Depends(require_ingest_token)])
def drift_keep(body: DriftActionIn):
    """An owner keeps the old scope (same rights check as `apply`)."""
    from pipeline.work import NotAllowed, keep_old_scope

    try:
        out = keep_old_scope(get_graph(), body.requirement, body.actor, body.reason)
    except NotAllowed as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    bus.publish("resolved", how="dismissed", requirement=body.requirement, by=body.actor)
    return out


@app.get("/api/tasks")
def list_tasks(person: str | None = None, status: str | None = "open"):
    from pipeline.work import tasks

    return tasks(get_graph(), person=person, status=status or None)


class TaskDoneIn(BaseModel):
    actor: str


@app.post("/api/tasks/{num}/done", dependencies=[Depends(require_ingest_token)])
def task_done(num: int, body: TaskDoneIn):
    from pipeline.work import NotAllowed, complete

    try:
        out = complete(get_graph(), num, body.actor)
    except NotAllowed as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    bus.publish("resolved", how="task done", task=out["task"], by=body.actor)
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
    return StreamingResponse(bus.stream(q), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/orgs")
def orgs():
    from graph.db import current_org, list_orgs

    return {"current": current_org(), "orgs": list_orgs()}


@app.post("/api/orgs/{org}/bootstrap", dependencies=[Depends(require_ingest_token)])
def bootstrap_org(org: str, extractor: str | None = None):
    """Creates (or rebuilds) an org's isolated graph from the demo data, so a new tenant can be tried at once.
    `extractor=heuristic` builds in seconds without LLM calls (the product tour uses it); default: the LLM if one answers.
    Also clears this org's alert cooldowns, so a restarted tour can raise its live alert again."""
    from graph.db import org_graph_name
    from pipeline import live, llm
    from pipeline.build import mark_build
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    try:
        name = org_graph_name(org)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if extractor not in (None, "heuristic", "llm"):
        raise HTTPException(400, "extractor must be heuristic or llm")
    extractor = extractor or ("llm" if llm.available() else "heuristic")
    for key in [k for k in live._last_alert if k[0] == org]:
        del live._last_alert[key]
    counts = ingest(reset=True, graph_name=name)
    g = get_graph(name)
    resolve(g, extractor, log=lambda *_: None)
    mark_build(g, extractor)
    from api.cache import clear as clear_cache

    clear_cache()  # a read cached just before the build (e.g. "is this sandbox empty?") must not outlive it
    return {"org": org, "graph": name, "extractor": extractor, "nodes": sum(counts["nodes"].values())}


@app.get("/api/metrics")
def metrics():
    """Prometheus text format: request counts and latency per route, cache, live clients, open drift per org."""
    from fastapi.responses import PlainTextResponse

    from graph.db import current_org

    hits, misses = cache_stats["hits"], cache_stats["misses"]
    extra = {
        "drift_cache_hits_total": hits,
        "drift_cache_misses_total": misses,
        "drift_event_bus_version": bus.version,
        "drift_sse_subscribers": len(bus._subscribers),
        f'drift_open_total{{org="{current_org()}"}}': len(_drift()),
    }
    return PlainTextResponse(render(extra), media_type="text/plain; version=0.0.4")


@app.get("/api/cache")
def cache_info():
    return {"version": bus.version, **cache_stats}


@app.get("/api/events/recent")
def recent_events():
    from graph.db import current_org

    return [e for e in bus.recent if e.get("org") == current_org()]  # tenants never see each other's events


@app.get("/api/tickets")
def tickets():
    return Q.rows(
        get_graph(),
        """MATCH (t:Ticket) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
                                  RETURN t.id AS id, t.title AS title, t.description AS description, t.state AS state,
                                         f.name AS feature ORDER BY id""",
    )


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
        raise HTTPException(404, str(e)) from e
    if out["status"] == "updated":
        bus.publish("ticket", ticket=body.ticket, by=body.actor, resolved=out["resolved"], still_drifting=out["still_drifting"])
    return out


class DocUpdateIn(BaseModel):
    doc: str
    text: str
    title: str | None = None
    actor: str = "maya"
    acl: list[str] | None = None  # who may see it: groups or person:<id>; [] = everyone; omitted = unchanged


@app.get("/api/docs")
def docs():
    """Documents with who may see them, their chunks (entries in the vector index), the tickets they mention and the
    open drift they are stale for. The response middleware leaves out every document the viewer may not see."""
    g = get_graph()
    stale: dict[str, set[str]] = {}
    for d in Q.drift(g):
        for s in d["stale_docs"]:
            stale.setdefault(s["id"], set()).add(d["ticket"])
    rows = Q.rows(
        g,
        """MATCH (d:Document) OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d) OPTIONAL MATCH (d)-[:MENTIONS]->(t:Ticket)
           WITH d, a, collect(DISTINCT t.id) AS tickets
           OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
           RETURN d.id AS id, d.title AS title, a.id AS author, d.updated AS updated, coalesce(d.acl, []) AS acl, d.text AS text,
                  tickets, collect([c.id, size(c.text), c.embedder]) AS chunks
           ORDER BY id""",
    )
    for r in rows:
        parts = sorted((c for c in r.pop("chunks") if c[0]), key=lambda c: int(c[0].rsplit("#", 1)[1]))
        r["chunks"] = [{"id": c[0], "chars": c[1]} for c in parts]
        r["embedder"] = parts[0][2] if parts else None
        r["tickets"] = sorted(r["tickets"])
        r["stale_for"] = sorted(stale.get(r["id"], ()))
    return rows


@app.get("/api/whoami")
def whoami():
    """The viewer this request acts for and the grants that decide what they may see."""
    from pipeline.access import current_viewer, grants

    return {"viewer": current_viewer(), "grants": grants(get_graph(), current_viewer())}


@app.post("/api/ingest/doc", dependencies=[Depends(require_ingest_token)])
def ingest_doc(body: DocUpdateIn):
    """Docs webhook (Notion/Confluence-style): a page's content changed. When the request acts for a person (X-User),
    that person must be able to see the doc: otherwise it answers exactly as for a doc that doesn't exist."""
    from pipeline.access import current_viewer, hidden
    from pipeline.webhooks import doc_updated

    if current_viewer() and body.doc in hidden(get_graph(), current_viewer())["ids"]:
        raise HTTPException(404, f"unknown doc {body.doc}")
    try:
        out = doc_updated(get_graph(), body.doc, body.text, body.actor, body.title, acl=body.acl)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    bus.publish("doc", doc=body.doc, by=body.actor, no_longer_stale=out["no_longer_stale"])
    return out


@app.post("/api/ingest/gdrive")
def ingest_gdrive(x_goog_channel_token: str | None = Header(default=None), x_goog_resource_state: str | None = Header(default=None)):
    """Google Drive push notification (changes.watch). It carries no content, so this runs one pass over the change
    feed (connectors/gdrive.py). Authenticated by the channel token set when the watch was created (GDRIVE_CHANNEL_TOKEN)."""
    import hmac
    import os

    expected = os.getenv("GDRIVE_CHANNEL_TOKEN", "")
    if not expected or not hmac.compare_digest(x_goog_channel_token or "", expected):
        raise HTTPException(401, "bad channel token")
    if x_goog_resource_state == "sync":  # the handshake Drive sends when a channel is created
        return {"status": "ok"}
    from connectors.gdrive import sync

    out = sync(get_graph())
    for d in out["updated"]:
        bus.publish("doc", doc=d, by="gdrive")
    return out


_seen_deliveries: dict[str, None] = {}  # recent X-GitHub-Delivery ids (insertion-ordered, capped): replays are ignored


@app.post("/api/ingest/github")
async def ingest_github(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_ingest_token: str | None = Header(default=None),
):
    """GitHub webhook (pull_request events). With GITHUB_WEBHOOK_SECRET set, the signature is the authentication
    (GitHub can't send our token header); without it, the usual INGEST_TOKEN check applies. A delivery id seen
    before is ignored, so a replayed payload can't roll a PR back."""
    import os

    from pipeline.webhooks import pr_event, verify_github_signature

    raw = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not verify_github_signature(secret, raw, x_hub_signature_256):
            raise HTTPException(401, "bad signature")
    else:
        require_ingest_token(authorization, x_ingest_token)
    if x_github_event and x_github_event != "pull_request":
        return {"status": "ignored", "event": x_github_event}
    if x_github_delivery:
        if x_github_delivery in _seen_deliveries:
            return {"status": "duplicate", "delivery": x_github_delivery}
        _seen_deliveries[x_github_delivery] = None
        while len(_seen_deliveries) > 1000:
            _seen_deliveries.pop(next(iter(_seen_deliveries)))
    import json

    from starlette.concurrency import run_in_threadpool

    try:
        out = await run_in_threadpool(pr_event, get_graph(), json.loads(raw or b"{}"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
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
