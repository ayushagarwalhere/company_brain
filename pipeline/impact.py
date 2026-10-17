"""Impact analysis and feature maps: what a delay ripples into, and everything around a feature, read from the graph.

Delay ("If we delay Project Alpha by two weeks, which teams and client deliverables are hit?"):
    Project -INCLUDES-> Ticket -BLOCKS->* Ticket <-INCLUDES- Project       downstream projects, at any depth
    Deliverable -NEEDS-> Project, Deliverable -FOR-> Client                   client commitments on those projects
    Person -AUTHORED-> Ticket, Ticket -ASSIGNED_TO-> Person,                  the people doing the delayed work,
    Person -AUTHORED-> PullRequest -REFERENCES-> Ticket, Person -OWNS-> ...   and their teams (Person -MEMBER_OF-> Team)
The schedule rule is deliberately simple: a delayed project launches N days later; a project waiting on it (through a
BLOCKS chain) can't launch before it; a deliverable misses when a project it needs now launches after its due date,
and is tight with less than TIGHT_DAYS of slack left. No task durations or partial overlaps: the traversal is the point.

Feature map: a feature's specs (every requirement version) with who introduced each, the tickets and docs that carry
them, the work on them (assignees, PRs and their authors, follow-up tasks), what depends on them (projects, blocked
tickets, deliverables, clients) and every person's team. Each node carries a column for the layered view.
"""

from graph import queries as Q
from pipeline.events import from_ms

DAY = 86_400_000
TIGHT_DAYS = 7


def _day(ms: int | None) -> str | None:
    return (from_ms(ms) or "")[:10] or None


def projects(g) -> list[dict]:
    """Every project with its launch date, owner, tickets, features and the client deliverables that need it."""
    rows = Q.rows(
        g,
        """MATCH (p:Project) OPTIONAL MATCH (o:Person)-[:OWNS]->(p)
           OPTIONAL MATCH (p)-[:INCLUDES]->(t:Ticket) OPTIONAL MATCH (t)-[:ABOUT]->(f:Feature)
           WITH p, o, collect(DISTINCT t.id) AS tickets, collect(DISTINCT f.id) AS features
           OPTIONAL MATCH (d:Deliverable)-[:NEEDS]->(p) OPTIONAL MATCH (d)-[:FOR]->(c:Client)
           RETURN p.id AS id, p.name AS name, p.about AS about, p.launch AS launch, o.id AS owner, tickets, features,
                  collect(DISTINCT [d.id, d.title, d.due, c.name]) AS deliverables
           ORDER BY launch""",
    )
    for r in rows:
        r["tickets"], r["features"] = sorted(r["tickets"]), sorted(r["features"])
        r["deliverables"] = [{"id": d[0], "title": d[1], "due": d[2], "client": d[3]} for d in r["deliverables"] if d[0]]
    return rows


def find_target(g, target: str) -> dict | None:
    """A project (id or name: 'alpha', 'Project Alpha'), a feature (id or name) or a ticket id."""
    raw = (target or "").strip()
    low = raw.lower().removeprefix("project ").strip()
    for p in Q.rows(g, "MATCH (p:Project) RETURN p.id AS id, p.name AS name"):
        if low and low in (p["id"].lower(), (p["name"] or "").lower().removeprefix("project ").strip()):
            ts = Q.rows(g, "MATCH (:Project {id: $p})-[:INCLUDES]->(t:Ticket) RETURN t.id AS t ORDER BY t", p=p["id"])
            return {"kind": "Project", "id": p["id"], "name": p["name"], "tickets": [r["t"] for r in ts]}
    f = Q.rows(g, "MATCH (f:Feature) WHERE toLower(f.id) = $l OR toLower(f.name) = $l RETURN f.id AS id, f.name AS name", l=raw.lower())
    if f:
        ts = Q.rows(g, "MATCH (t:Ticket)-[:ABOUT]->(:Feature {id: $f}) RETURN DISTINCT t.id AS t ORDER BY t", f=f[0]["id"])
        return {"kind": "Feature", "id": f[0]["id"], "name": f[0]["name"], "tickets": [r["t"] for r in ts]}
    t = Q.rows(g, "MATCH (t:Ticket {id: $id}) RETURN t.id AS id, t.title AS name", id=raw.upper())
    if t:
        return {"kind": "Ticket", "id": t[0]["id"], "name": t[0]["name"], "tickets": [t[0]["id"]]}
    return None


def impact_of_delay(g, target: str, days: int = 14) -> dict:
    """What slips, who is hit and which client commitments are at risk if `target` is delayed by `days`."""
    tgt = find_target(g, target)
    if not tgt:
        return {"target": None, "error": f"no project, feature or ticket called {target!r}", "paths": []}
    days, delta = max(0, int(days)), max(0, int(days)) * DAY
    proj = {r["id"]: r for r in Q.rows(g, "MATCH (p:Project) RETURN p.id AS id, p.name AS name, p.launch_ms AS launch_ms")}
    proj_of: dict[str, list[str]] = {}
    for r in Q.rows(g, "MATCH (p:Project)-[:INCLUDES]->(t:Ticket) RETURN p.id AS p, t.id AS t"):
        proj_of.setdefault(r["t"], []).append(r["p"])
    # everything downstream of the delayed tickets, at any depth, in one variable-length traversal
    walks = Q.rows(
        g,
        """MATCH path = (a:Ticket)-[:BLOCKS*1..8]->(b:Ticket) WHERE a.id IN $ts
           RETURN [n IN nodes(path) | n.id] AS chain, [r IN relationships(path) | r.why] AS why ORDER BY size(chain)""",
        ts=tgt["tickets"],
    )

    # the schedule: the delayed projects move by `days`; whatever waits on them (BLOCKS, any depth) can't launch earlier
    roots = [tgt["id"]] if tgt["kind"] == "Project" else sorted({p for t in tgt["tickets"] for p in proj_of.get(t, [])})
    new = {p: proj[p]["launch_ms"] + delta for p in roots}
    late = set(tgt["tickets"])
    ready = {t: max([new[p] for p in proj_of.get(t, []) if p in new], default=None) for t in late}
    chains, via = [], {}
    for w in walks:  # shortest walks first, so each hop's upstream date is known when it is reached
        for a, b, why in zip(w["chain"], w["chain"][1:], w["why"], strict=False):
            if b in late:
                continue
            e = {"a": a, "b": b, "why": why}
            late.add(b)
            chains.append(e)
            up = ready.get(a)
            for p in proj_of.get(b, []):
                if p not in new and p not in via:
                    via[p] = e
                if up is not None and up > new.get(p, proj[p]["launch_ms"]):
                    new[p] = up
            ready[b] = max([new.get(p, proj[p]["launch_ms"]) for p in proj_of.get(b, [])], default=up)
    downstream = sorted({p for t in late for p in proj_of.get(t, [])} - set(roots), key=lambda p: proj[p]["launch_ms"])
    projects_out = [
        {
            "id": p,
            "name": proj[p]["name"],
            "launch": _day(proj[p]["launch_ms"]),
            "new_launch": _day(new.get(p, proj[p]["launch_ms"])),
            "slip_days": (new.get(p, proj[p]["launch_ms"]) - proj[p]["launch_ms"]) // DAY,
            "root": p in roots,
            "via": None if p in roots or p not in via else {"from": via[p]["a"], "to": via[p]["b"], "why": via[p]["why"]},
        }
        for p in roots + downstream
    ]

    deliverables = []
    for d in Q.rows(
        g,
        """MATCH (d:Deliverable)-[:NEEDS]->(p:Project) WHERE p.id IN $ps
           WITH DISTINCT d MATCH (d)-[:FOR]->(c:Client) MATCH (d)-[:NEEDS]->(q:Project) OPTIONAL MATCH (o:Person)-[:OWNS]->(d)
           RETURN d.id AS id, d.title AS title, d.due AS due, d.due_ms AS due_ms, c.id AS client, c.name AS client_name,
                  o.id AS owner, collect(DISTINCT q.id) AS needs""",
        ps=[p["id"] for p in projects_out],
    ):
        before = max(proj[q]["launch_ms"] for q in d["needs"])
        after = max(new.get(q, proj[q]["launch_ms"]) for q in d["needs"])
        slack = (d["due_ms"] - after) // DAY
        status = "misses" if slack < 0 else "tight" if slack < TIGHT_DAYS else "on track"
        deliverables.append(
            {
                **{k: d[k] for k in ("id", "title", "due", "client", "client_name", "owner", "needs")},
                "ready": _day(after),
                "moved": after > before,
                "slack_days": slack,
                "status": status,
            }
        )
    deliverables.sort(key=lambda d: (not d["moved"], d["slack_days"]))
    hit = [d for d in deliverables if d["moved"]]

    ts, ps = sorted(late), [p["id"] for p in projects_out if p["root"] or p["slip_days"] > 0]
    work = Q.rows(
        g,
        """MATCH (p:Person)-[:AUTHORED]->(t:Ticket) WHERE t.id IN $ts RETURN p.id AS person, 'created ' + t.id AS role, t.id AS ticket
           UNION ALL MATCH (t:Ticket)-[:ASSIGNED_TO]->(p:Person) WHERE t.id IN $ts RETURN p.id AS person, 'assigned ' + t.id AS role, t.id AS ticket
           UNION ALL MATCH (p:Person)-[:AUTHORED]->(pr:PullRequest)-[:REFERENCES]->(t:Ticket) WHERE t.id IN $ts
                     RETURN p.id AS person, 'PR #' + toString(pr.number) + ' on ' + t.id AS role, t.id AS ticket
           UNION ALL MATCH (p:Person)-[:OWNS]->(j:Project) WHERE j.id IN $ps RETURN p.id AS person, 'owns ' + j.name AS role, null AS ticket
           UNION ALL MATCH (p:Person)-[:OWNS]->(d:Deliverable) WHERE d.id IN $ds RETURN p.id AS person, 'owns ' + d.title AS role, null AS ticket""",
        ts=ts,
        ps=ps,
        ds=[d["id"] for d in hit],
    )
    people = sorted({w["person"] for w in work})
    member = {
        r["p"]: r
        for r in Q.rows(
            g,
            "MATCH (p:Person) WHERE p.id IN $ids OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team) RETURN p.id AS p, p.name AS name, t.id AS team, t.name AS team_name",
            ids=people,
        )
    }
    teams: dict[str, dict] = {}
    for pid in people:
        m = member.get(pid) or {"name": pid, "team": None, "team_name": None}
        team = teams.setdefault(m["team"] or "none", {"id": m["team"], "name": m["team_name"] or "No team", "people": []})
        roles = sorted({w["role"] for w in work if w["person"] == pid})
        team["people"].append(
            {"id": pid, "name": m["name"], "roles": roles, "tickets": sorted({w["ticket"] for w in work if w["person"] == pid and w["ticket"]})}
        )
    teams_out = sorted(teams.values(), key=lambda t: (-len(t["people"]), t["name"]))

    titles = {
        r["id"]: r
        for r in Q.rows(
            g,
            "MATCH (t:Ticket) WHERE t.id IN $ts OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person) RETURN t.id AS id, t.title AS title, t.state AS state, a.id AS assignee",
            ts=ts,
        )
    }
    tickets_out = [{**titles[t], "root": t in tgt["tickets"], "blocked_by": sorted(e["a"] for e in chains if e["b"] == t)} for t in ts if t in titles]
    drift = [{"ticket": d["ticket"], "text": d["requirement_text"], "by": d["changed_by"]} for d in Q.drift(g) if d["ticket"] in late]

    # evidence: the paths that make each claim true
    paths = []
    root_label = f"Project {roots[0]}" if roots else f"{tgt['kind']} {tgt['id']}"
    for d in hit:
        need = next((q for q in d["needs"] if q in new), d["needs"][0])
        paths.append(f"(Client {d['client']})<-[:FOR]-(Deliverable {d['id']})-[:NEEDS]->(Project {need})")
    for e in chains:
        for p in proj_of.get(e["b"], []):
            if p not in roots:
                src = next(iter(proj_of.get(e["a"], [])), None)
                paths.append((f"(Project {src})-[:INCLUDES]->" if src else "") + f"(Ticket {e['a']})-[:BLOCKS]->(Ticket {e['b']})<-[:INCLUDES]-(Project {p})")
    for t in teams_out:
        for person in t["people"]:
            if person["tickets"] and t["id"]:
                tk = person["tickets"][0]
                rel = "-[:ASSIGNED_TO]->" if any(r.startswith("assigned " + tk) for r in person["roles"]) else "<-[:AUTHORED]-"
                src = next(iter(proj_of.get(tk, [])), None)
                paths.append((f"(Project {src})-[:INCLUDES]->" if src else "") + f"(Ticket {tk}){rel}(Person {person['id']})-[:MEMBER_OF]->(Team {t['id']})")
                break

    return {
        "target": {k: tgt[k] for k in ("kind", "id", "name")},
        "root": root_label,
        "days": days,
        "projects": projects_out,
        "tickets": tickets_out,
        "deliverables": deliverables,
        "teams": teams_out,
        "drift": drift,
        "paths": paths,
        "graph": _impact_graph(projects_out, tickets_out, chains, proj_of, deliverables, teams_out, work),
    }


def _impact_graph(projects_out, tickets_out, chains, proj_of, deliverables, teams_out, work) -> dict:
    """Nodes in columns: Team | Person | delayed project | its tickets | blocked tickets | waiting projects | deliverables | clients."""
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(nid, type_, label, col, **extra):
        nodes.setdefault(nid, {"id": nid, "type": type_, "label": label, "col": col, **extra})

    pids = {p["id"] for p in projects_out}
    for p in projects_out:
        status = "delayed" if p["root"] else "slips" if p["slip_days"] > 0 else "waits"
        node(p["id"], "Project", p["name"], 2 if p["root"] else 5, status=status, text=f"launch {p['launch']} → {p['new_launch']}")
    for t in tickets_out:
        node(t["id"], "Ticket", t["id"], 3 if t["root"] else 4, status="late", text=t["title"])
        for p in proj_of.get(t["id"], []):
            if p in pids:
                edges.add((p, "INCLUDES", t["id"]))
    for e in chains:
        edges.add((e["a"], "BLOCKS", e["b"]))
    for d in deliverables:
        node(d["id"], "Deliverable", d["title"], 6, status=d["status"] if d["moved"] else "unaffected", text=f"due {d['due']} · ready {d['ready']}")
        node(d["client"], "Client", d["client_name"], 7)
        edges.add((d["id"], "FOR", d["client"]))
        for q in d["needs"]:
            if q in pids:
                edges.add((d["id"], "NEEDS", q))
    order = {"misses": 0, "tight": 1, "on track": 2, "unaffected": 3}
    for d in deliverables:  # a client is as at risk as its worst deliverable
        c = nodes[d["client"]]
        st = nodes[d["id"]]["status"]
        if "status" not in c or order[st] < order[c["status"]]:
            c["status"] = st
    for t in teams_out:
        if t["id"]:
            node(f"team:{t['id']}", "Team", t["name"], 0)
        for person in t["people"]:
            node(person["id"], "Person", person["name"], 1, text=", ".join(person["roles"]))
            if t["id"]:
                edges.add((person["id"], "MEMBER_OF", f"team:{t['id']}"))
    for w in work:
        if w["ticket"] and w["ticket"] in nodes:
            rel = "ASSIGNED_TO" if w["role"].startswith("assigned") else "AUTHORED"
            edges.add((w["ticket"], rel, w["person"]) if rel == "ASSIGNED_TO" else (w["person"], rel, w["ticket"]))
        elif w["role"].startswith("owns "):
            target = next((d["id"] for d in deliverables if w["role"] == f"owns {d['title']}"), None) or next(
                (p["id"] for p in projects_out if w["role"] == f"owns {p['name']}"), None
            )
            if target:
                edges.add((w["person"], "OWNS", target))
    return {"nodes": list(nodes.values()), "edges": [{"from": a, "rel": r, "to": b} for a, r, b in sorted(edges)]}


def feature_map(g, feature: str) -> dict:
    """Everything around a feature, in columns: Team | Person | specs | tickets & docs | work | projects | deliverables | clients."""
    f = Q.rows(g, "MATCH (f:Feature {id: $f}) RETURN f.id AS id, f.name AS name", f=feature)
    if not f:
        return {"nodes": [], "edges": []}
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(nid, type_, label, col, **extra):
        if nid is None:
            return None
        nodes.setdefault(nid, {"id": nid, "type": type_, "label": label, "col": col, **extra})
        return nid

    node(feature, "Feature", f[0]["name"], 5)
    tickets = Q.rows(
        g,
        """MATCH (t:Ticket)-[:ABOUT]->(:Feature {id: $f}) OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a:Person)
           RETURN DISTINCT t.id AS id, t.title AS title, t.state AS state, t.description AS text, c.id AS creator, a.id AS assignee,
                  coalesce(t.version_actors, []) AS actors ORDER BY id""",
        f=feature,
    )
    ids = [t["id"] for t in tickets]
    open_drift = {d["requirement"] for d in Q.drift(g, feature=feature)}
    for t in tickets:
        node(t["id"], "Ticket", t["id"], 3, text=f"{t['title']} ({t['state']})")
        edges.add((t["id"], "ABOUT", feature))
        if t["assignee"]:
            edges.add((t["id"], "ASSIGNED_TO", t["assignee"]))
    # specs: every requirement version, with who introduced it (ticket versions: who wrote that version; chat: who said it)
    for r in Q.rows(
        g,
        """MATCH (t:Ticket)-[:STATES]->(q:Requirement) WHERE t.id IN $ids
           OPTIONAL MATCH (sup:Requirement)-[:SUPERSEDES]->(q) OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(q)
           RETURN t.id AS ticket, q.id AS id, q.text AS text, q.written_by AS by, count(DISTINCT sup) AS superseded, count(DISTINCT pr) AS shipped, 'ticket' AS origin
           UNION ALL
           MATCH (q:Requirement)-[:AMENDS]->(t:Ticket) WHERE t.id IN $ids
           OPTIONAL MATCH (p:Person)-[:POSTED]->(:Message)-[:CHANGES]->(q)
           OPTIONAL MATCH (sup:Requirement)-[:SUPERSEDES]->(q) OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(q)
           RETURN t.id AS ticket, q.id AS id, q.text AS text, p.id AS by, count(DISTINCT sup) AS superseded, count(DISTINCT pr) AS shipped, 'chat' AS origin""",
        ids=ids,
    ):
        tk = next(t for t in tickets if t["id"] == r["ticket"])
        by = r["by"]
        if not by and r["origin"] == "ticket":
            n = int(r["id"].rsplit(":v", 1)[1]) if ":v" in r["id"] else 1
            by = tk["actors"][n - 1] if n <= len(tk["actors"]) else tk["creator"]
        status = "drift" if r["id"] in open_drift else "superseded" if r["superseded"] else "shipped" if r["shipped"] else "current"
        label = r["id"].replace("req:", "").replace(":v", " v") if r["origin"] == "ticket" else "chat change"
        node(r["id"], "Requirement", label, 2, text=r["text"], status=status, drift=status == "drift")
        edges.add((r["ticket"], "STATES", r["id"]) if r["origin"] == "ticket" else (r["id"], "AMENDS", r["ticket"]))
        if by:
            edges.add((by, "INTRODUCED", r["id"]))
    for e in Q.rows(g, "MATCH (a:Requirement)-[:SUPERSEDES]->(b:Requirement) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS a, b.id AS b", ids=list(nodes)):
        edges.add((e["a"], "SUPERSEDES", e["b"]))
    # the work: PRs and their authors, follow-up tasks, docs and their authors
    for r in Q.rows(
        g,
        """MATCH (pr:PullRequest)-[:REFERENCES]->(t:Ticket) WHERE t.id IN $ids OPTIONAL MATCH (a:Person)-[:AUTHORED]->(pr)
           OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(q:Requirement)
           RETURN pr.id AS id, pr.number AS n, pr.title AS title, t.id AS ticket, a.id AS author, collect(DISTINCT q.id) AS impl""",
        ids=ids,
    ):
        node(r["id"], "PullRequest", f"PR #{r['n']}", 4, text=r["title"])
        edges.add((r["id"], "REFERENCES", r["ticket"]))
        if r["author"]:
            edges.add((r["author"], "AUTHORED", r["id"]))
        for q in r["impl"]:
            if q in nodes:
                edges.add((r["id"], "IMPLEMENTS", q))
    for r in Q.rows(
        g,
        """MATCH (d:Document)-[:MENTIONS]->(t:Ticket) WHERE t.id IN $ids OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)
           RETURN DISTINCT d.id AS id, d.title AS title, t.id AS ticket, a.id AS author""",
        ids=ids,
    ):
        node(r["id"], "Document", r["id"], 3, text=r["title"])
        edges.add((r["id"], "MENTIONS", r["ticket"]))
        if r["author"]:
            edges.add((r["author"], "AUTHORED", r["id"]))
    for r in Q.rows(
        g,
        """MATCH (k:Task)-[:FOR]->(q:Requirement) WHERE q.id IN $reqs OPTIONAL MATCH (k)-[:ASSIGNED_TO]->(a:Person) OPTIONAL MATCH (k)-[:FIXES]->(x)
           RETURN k.id AS id, k.num AS num, k.title AS title, k.status AS status, a.id AS assignee, x.id AS target, q.id AS req""",
        reqs=[n for n, v in nodes.items() if v["type"] == "Requirement"],
    ):
        node(r["id"], "Task", f"T-{r['num']}", 4, text=f"{r['title']} ({r['status']})", status=r["status"])
        edges.add((r["id"], "FOR", r["req"]))
        if r["assignee"]:
            edges.add((r["id"], "ASSIGNED_TO", r["assignee"]))
        if r["target"] in nodes:
            edges.add((r["id"], "FIXES", r["target"]))
    # what depends on it: projects, blocked tickets elsewhere, deliverables, clients
    for r in Q.rows(
        g,
        "MATCH (p:Project)-[:INCLUDES]->(t:Ticket) WHERE t.id IN $ids RETURN p.id AS id, p.name AS name, p.launch AS launch, collect(t.id) AS tickets",
        ids=ids,
    ):
        node(r["id"], "Project", r["name"], 5, text=f"launch {r['launch']}")
        for tid in r["tickets"]:
            edges.add((r["id"], "INCLUDES", tid))
    for r in Q.rows(
        g,
        """MATCH (a:Ticket)-[:BLOCKS]->(b:Ticket) WHERE a.id IN $ids OR b.id IN $ids
           RETURN a.id AS a, b.id AS b, a.title AS at, b.title AS bt""",
        ids=ids,
    ):
        node(r["a"], "Ticket", r["a"], 3, text=r["at"])
        node(r["b"], "Ticket", r["b"], 3, text=r["bt"])
        edges.add((r["a"], "BLOCKS", r["b"]))
    for r in Q.rows(
        g,
        """MATCH (d:Deliverable)-[:NEEDS]->(p:Project) WHERE p.id IN $ps MATCH (d)-[:FOR]->(c:Client)
           RETURN d.id AS id, d.title AS title, d.due AS due, p.id AS project, c.id AS client, c.name AS client_name""",
        ps=[n for n, v in nodes.items() if v["type"] == "Project"],
    ):
        node(r["id"], "Deliverable", r["title"], 6, text=f"due {r['due']}")
        node(r["client"], "Client", r["client_name"], 7)
        edges.add((r["id"], "NEEDS", r["project"]))
        edges.add((r["id"], "FOR", r["client"]))
    # people and their teams (everyone the edges above name)
    people = sorted({a for a, _, _ in edges if a not in nodes} | {b for _, rel, b in edges if rel == "ASSIGNED_TO"})
    for r in Q.rows(
        g,
        "MATCH (p:Person) WHERE p.id IN $ids OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team) RETURN p.id AS id, p.name AS name, p.role AS role, t.id AS team, t.name AS team_name",
        ids=people,
    ):
        node(r["id"], "Person", r["name"] or r["id"], 1, text=r["role"])
        if r["team"]:
            node(f"team:{r['team']}", "Team", r["team_name"], 0)
            edges.add((r["id"], "MEMBER_OF", f"team:{r['team']}"))
    return {"nodes": list(nodes.values()), "edges": [{"from": a, "rel": r, "to": b} for a, r, b in sorted(edges) if a in nodes and b in nodes]}
