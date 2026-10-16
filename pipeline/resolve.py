"""Phase 4: entity resolution + requirement graph.

Turns the base graph (people, messages, tickets, PRs) into the context graph:

  Feature      <-ABOUT-     Ticket, PullRequest, Message, Requirement
  Ticket       -STATES->    Requirement   (one per description version)
  Message      -CHANGES->   Requirement   -AMENDS-> Ticket   (chat changed what the ticket says)
  Decision     -CHANGES->   Requirement,  Person -MADE-> Decision -RECORDED_IN-> Message
  Requirement  -SUPERSEDES-> Requirement  (per ticket, newest -> older)
  PullRequest  -IMPLEMENTS-> Requirement

Resolution signals, applied in order, each recorded on the edge as `via`:
  1. hard       ticket ids in text (MENTIONS / REFERENCES from ingestion)
  2. proximity  thread structure for messages; shared person + time window for PRs
  3. semantic   LLM feature guess (deepseek) or TF-IDF over feature text (fallback)
"""
from collections import defaultdict

from pipeline.events import from_ms
from pipeline.extract import CHANGE_KINDS, get_extractor
from pipeline.textsim import TfIdf, tokens

MIN_CONFIDENCE = 0.6  # below this an extracted "change" is not written (same bar as the live monitor)
MSG_SIM_THRESHOLD = 0.22
PR_SIM_THRESHOLD = 0.25
DAY_MS = 86_400_000


# ---------------------------------------------------------------- reads

def _rows(g, q, params=None):
    res = g.query(q, params or {})
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


PAGE = 5000  # FalkorDB caps result sets (RESULTSET_SIZE, 10k in the Docker image): large reads must page


def _rows_paged(g, q, params=None, page: int = PAGE):
    """Runs a query that ends in a stable ORDER BY, page by page, so no server-side cap truncates it."""
    out, skip = [], 0
    while True:
        batch = _rows(g, q + " SKIP $_skip LIMIT $_limit", {**(params or {}), "_skip": skip, "_limit": page})
        out += batch
        if len(batch) < page:
            return out
        skip += page


def load_tickets(g):
    return _rows(g, """MATCH (t:Ticket) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person)
                       OPTIONAL MATCH (c:Person)-[:AUTHORED]->(t)
                       RETURN t.id AS id, c.id AS creator, t.title AS title, t.description AS description,
                              t.versions AS versions, t.version_times AS version_times, t.labels AS labels,
                              t.created_ms AS created_ms, t.completed_ms AS completed_ms, p.id AS assignee
                       ORDER BY t.id""")


def load_messages(g):
    return _rows_paged(g, """MATCH (a:Person)-[:POSTED]->(m:Message)
                       OPTIONAL MATCH (m)-[:REPLY_TO]->(parent:Message)
                       OPTIONAL MATCH (m)-[:MENTIONS]->(t:Ticket)
                       RETURN m.id AS id, m.text AS text, m.ts AS ts, m.ts_ms AS ts_ms, m.channel AS channel,
                              m.source AS source, a.id AS author, parent.id AS parent, collect(t.id) AS mentions
                       ORDER BY ts_ms, id""")


def load_prs(g):
    return _rows(g, """MATCH (a:Person)-[:AUTHORED]->(pr:PullRequest)
                       OPTIONAL MATCH (pr)-[:REFERENCES]->(t:Ticket)
                       RETURN pr.id AS id, pr.number AS number, pr.title AS title, pr.body AS body,
                              pr.created_ms AS created_ms, pr.merged_ms AS merged_ms, a.id AS author,
                              collect(t.id) AS refs
                       ORDER BY pr.number""")


# ---------------------------------------------------------------- resolution

def supersession_pairs(chain: list[dict], reflects, replaces=None) -> list[dict]:
    """SUPERSEDES edges for one ticket's requirements (chronological).

    Each new requirement supersedes the current heads it actually replaces; the rest stay open:
      * anything supersedes an older ticket version;
      * a ticket version supersedes a chat change only if its text reflects that change, so an
        unrelated edit (typo fix, new label) can't silently hide drift;
      * a chat change supersedes an older chat change only if `replaces(new, old)` says it revises
        that decision AND it is at least as confident. Without a judge (`replaces=None`, the rules
        extractor) chat never supersedes chat: being the latest message is not evidence. This is the
        fix for benchmark/noise.py, where a misread status update used to bury the real decision.
    """
    pairs, heads, last_ticket_text = [], [], ""
    for r in chain:
        if r["origin"] == "ticket":
            r = {**r, "prev_text": last_ticket_text}  # lets reflects() look at what this edit added
            last_ticket_text = r["text"]
        keep = []
        for h in heads:
            if h["origin"] == "ticket":
                ok = True
            elif r["origin"] == "ticket":
                ok = reflects(r, h)
            else:
                ok = (replaces is not None and (r.get("confidence") or 0) >= (h.get("confidence") or 0)
                      and replaces(r, h))
            if ok:
                pairs.append({"new": r["id"], "old": h["id"]})
            else:
                keep.append(h)
        heads = [r] + keep
    return pairs


def reset_derived(g):
    """Drops everything resolve() derives. Human Decisions (origin 'human') stay; relink() re-attaches them."""
    for label in ("Feature", "Requirement"):
        g.query(f"MATCH (n:{label}) DETACH DELETE n")
    g.query("MATCH (n:Decision) WHERE coalesce(n.origin, 'extractor') <> 'human' DETACH DELETE n")
    g.query("MATCH ()-[r:ABOUT]->() DELETE r")
    g.query("MATCH ()-[r:REFERENCES]->() WHERE r.via = 'resolved' DELETE r")


ABLATIONS = {"threads", "pr_proximity", "semantic", "supersession"}


def has_decision_rights(author: str | None, ticket: dict) -> bool:
    """Only a ticket's owners can change its requirement from chat: whoever created it (AUTHORED)
    or is assigned to it (ASSIGNED_TO). Status updates, review remarks, proposals and customer requests
    from anyone else stay plain messages. Measured in benchmark/noise.py."""
    return author is not None and author in (ticket.get("creator"), ticket.get("assignee"))


def resolve(g, extractor_name: str = "llm", semantic: str | None = None, log=print,
            ablate: frozenset = frozenset(), decision_rights: bool = True, latest_wins: bool = False) -> dict:
    """`ablate` switches off graph capabilities one at a time (benchmark/ablation.py):
    threads (REPLY_TO), pr_proximity (author + time window), semantic, supersession (SUPERSEDES/IMPLEMENTS).
    `decision_rights=False` lets anyone's chat message change any ticket, and `latest_wins=True` lets every chat
    change supersede the open ones: both are the behaviour before benchmark/noise.py, kept to reproduce it."""
    assert set(ablate) <= ABLATIONS, ablate
    ex = get_extractor(extractor_name)
    semantic = semantic or ("llm" if extractor_name in ("llm", "deepseek") else "tfidf")
    reset_derived(g)
    tickets = load_tickets(g)
    tix = {t["id"]: t for t in tickets}

    # 1. Features from tickets ------------------------------------------------
    features = ex.group_tickets([{"id": t["id"], "title": t["title"], "description": t["description"],
                                  "labels": t["labels"] or []} for t in tickets])
    feat_of_ticket = {}
    for f in features:
        f["tickets"] = [t for t in f["tickets"] if t in tix]
        for t in f["tickets"]:
            feat_of_ticket[t] = f["id"]
    g.query("UNWIND $fs AS f MERGE (x:Feature {id: f.id}) SET x.name = f.name", {"fs": features})
    g.query("""UNWIND $pairs AS p MATCH (t:Ticket {id: p.t}), (f:Feature {id: p.f})
               MERGE (t)-[:ABOUT {via: 'grouping'}]->(f)""",
            {"pairs": [{"t": t, "f": f} for t, f in feat_of_ticket.items()]})
    log(f"features: {len(features)} ({', '.join(f['id'] for f in features)})")

    # 2. Ticket requirements: one Requirement per description version ----------
    req_rows = []
    for t in tickets:
        for i, (text, at) in enumerate(zip(t["versions"] or [t["description"]], t["version_times"] or [t["created_ms"]])):
            req_rows.append({"id": f"req:{t['id']}:v{i + 1}", "ticket": t["id"], "text": text, "at_ms": at,
                             "at": from_ms(at), "feature": feat_of_ticket.get(t["id"])})
    g.query("""UNWIND $rs AS r MATCH (t:Ticket {id: r.ticket})
               MERGE (q:Requirement {id: r.id})
               SET q.text = r.text, q.at_ms = r.at_ms, q.at = r.at, q.origin = 'ticket', q.ticket = r.ticket
               MERGE (t)-[:STATES {at_ms: r.at_ms}]->(q)""", {"rs": req_rows})
    g.query("""UNWIND $rs AS r WITH r WHERE r.feature IS NOT NULL
               MATCH (q:Requirement {id: r.id}), (f:Feature {id: r.feature}) MERGE (q)-[:ABOUT]->(f)""", {"rs": req_rows})

    # 3. PRs -> tickets (proximity + semantic for unlinked) -> features ---------
    prs = load_prs(g)
    ticket_sim = TfIdf({t["id"]: f"{t['title']} {t['description']}" for t in tickets})
    pr_links = {}
    for pr in prs:
        if pr["refs"]:
            pr_links[pr["id"]] = [(r, "hard", 1.0) for r in pr["refs"]]
            continue
        at = pr["created_ms"]
        # proximity: tickets owned by the PR author that were open around the PR's time
        cands = [t["id"] for t in tickets if t["assignee"] == pr["author"] and t["created_ms"] <= at
                 and (t["completed_ms"] is None or t["completed_ms"] >= at - DAY_MS)]
        if "pr_proximity" in ablate:  # text similarity alone, over every ticket that existed
            cands = [t["id"] for t in tickets if t["created_ms"] <= at]
        best, score = ticket_sim.best(f"{pr['title']} {pr['body']}", among=cands)
        if best and score >= PR_SIM_THRESHOLD:
            pr_links[pr["id"]] = [(best, "proximity+semantic", round(score, 3))]
    g.query("""UNWIND $ls AS l MATCH (pr:PullRequest {id: l.pr}), (t:Ticket {id: l.t})
               MERGE (pr)-[r:REFERENCES]->(t) ON CREATE SET r.via = 'resolved', r.how = l.via, r.score = l.score""",
            {"ls": [{"pr": p, "t": t, "via": v, "score": s} for p, ls in pr_links.items() for t, v, s in ls if v != "hard"]})
    pr_feature = {}
    for p, ls in pr_links.items():
        for t, via, _ in ls:
            if t in feat_of_ticket:
                pr_feature[p] = (feat_of_ticket[t], via)
    g.query("""UNWIND $ps AS p MATCH (pr:PullRequest {id: p.pr}), (f:Feature {id: p.f})
               MERGE (pr)-[:ABOUT {via: p.via}]->(f)""",
            {"ps": [{"pr": p, "f": f, "via": v} for p, (f, v) in pr_feature.items()]})

    # Docs: hard link through the tickets they mention
    g.query("""MATCH (d:Document)-[:MENTIONS]->(:Ticket)-[:ABOUT]->(f:Feature)
               MERGE (d)-[:ABOUT {via: 'hard'}]->(f)""")

    # 4. Messages -> features ---------------------------------------------------
    msgs = load_messages(g)
    by_id = {m["id"]: m for m in msgs}

    def root(mid):
        if "threads" in ablate:
            return mid
        seen = set()
        while by_id.get(mid, {}).get("parent") and mid not in seen:
            seen.add(mid)
            mid = by_id[mid]["parent"]
        return mid

    threads = defaultdict(list)
    for m in msgs:
        threads[root(m["id"])].append(m)

    # Extraction first: the LLM also proposes a feature (semantic signal) for deepseek mode
    feat_ctx = [{**f, "ticket_objs": [{"id": t, "title": tix[t]["title"], "description": tix[t]["description"]}
                                      for t in f["tickets"]]} for f in features]
    items = []
    for m in msgs:
        if len(tokens(m["text"])) < 3 and not m["mentions"]:
            continue
        thread = [x for x in threads[root(m["id"])] if x["ts_ms"] < m["ts_ms"]][-6:]
        items.append({"id": m["id"], "author": m["author"], "ts": m["ts"], "text": m["text"],
                      "thread": [{"author": x["author"], "text": x["text"]} for x in thread]})
    log(f"classifying {len(items)} messages with {ex.name} ...")
    cls = ex.classify(items, feat_ctx)

    feat_docs = {}
    for f in features:
        parts = [f"{tix[t]['title']} {' '.join(tix[t]['versions'] or [tix[t]['description']])}" for t in f["tickets"]]
        parts += [f"{pr['title']} {pr['body']}" for pr in prs if pr_feature.get(pr["id"], (None,))[0] == f["id"]]
        feat_docs[f["id"]] = " ".join(parts)
    feat_sim = TfIdf(feat_docs) if feat_docs else None

    msg_feature: dict[str, tuple[str, str]] = {}
    for m in msgs:  # signal 1: hard
        fs = [feat_of_ticket[t] for t in m["mentions"] if t in feat_of_ticket]
        if fs:
            msg_feature[m["id"]] = (fs[0], "hard")
    for r, members in threads.items():  # signal 2: proximity (same thread)
        linked = [msg_feature[x["id"]][0] for x in members if x["id"] in msg_feature]
        if linked:
            for x in members:
                msg_feature.setdefault(x["id"], (linked[0], "thread"))
    for m in msgs:  # signal 3: semantic
        # a hard link to a ticket outside every feature is still a resolution: don't guess further
        if m["id"] in msg_feature or m["mentions"] or "semantic" in ablate:
            continue
        if semantic == "llm":
            f = (cls.get(m["id"]) or {}).get("feature")
            if f in feat_docs:
                msg_feature[m["id"]] = (f, "semantic:llm")
        elif feat_sim:
            f, s = feat_sim.best(m["text"])
            if f and s >= MSG_SIM_THRESHOLD:
                msg_feature[m["id"]] = (f, f"semantic:tfidf:{s:.2f}")
    # a root that got a feature semantically passes it to its unlinked replies
    for r, members in threads.items():
        if r in msg_feature:
            for x in members:
                msg_feature.setdefault(x["id"], (msg_feature[r][0], "thread"))
    g.query("""UNWIND $ms AS x MATCH (m:Message {id: x.m}), (f:Feature {id: x.f})
               MERGE (m)-[:ABOUT {via: x.via}]->(f)""",
            {"ms": [{"m": m, "f": f, "via": v} for m, (f, v) in msg_feature.items()]})

    # 5. Requirement changes and decisions from chat ------------------------------
    changes = []
    for m in msgs:
        c = cls.get(m["id"]) or {}
        if c.get("kind") not in CHANGE_KINDS or not c.get("requirement") or (c.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        feat = msg_feature.get(m["id"], (c.get("feature"), "llm"))[0] or c.get("feature")
        if feat not in feat_docs:
            continue
        f_tickets = [t for t in next(f for f in features if f["id"] == feat)["tickets"] if tix[t]["created_ms"] <= m["ts_ms"]]
        thread_mentions = [t for x in threads[root(m["id"])] for t in x["mentions"]]
        ticket = c.get("ticket") if c.get("ticket") in f_tickets else None
        ticket = ticket or next((t for t in m["mentions"] + thread_mentions if t in f_tickets), None)
        if not ticket and f_tickets:
            ticket, _ = ticket_sim.best(f"{c['requirement']} {m['text']}", among=f_tickets)
        if not ticket or (decision_rights and not has_decision_rights(m["author"], tix[ticket])):
            continue
        changes.append({"id": f"req:{m['id']}", "msg": m["id"], "author": m["author"], "ticket": ticket,
                        "feature": feat, "text": c["requirement"], "at_ms": m["ts_ms"], "at": m["ts"],
                        "decision": c["kind"] == "decision", "confidence": c.get("confidence")})
    g.query("""UNWIND $cs AS c
               MATCH (m:Message {id: c.msg}), (t:Ticket {id: c.ticket}), (f:Feature {id: c.feature})
               MERGE (q:Requirement {id: c.id})
               SET q.text = c.text, q.at_ms = c.at_ms, q.at = c.at, q.origin = 'chat', q.ticket = c.ticket,
                   q.confidence = c.confidence
               MERGE (m)-[:CHANGES {at_ms: c.at_ms}]->(q)
               MERGE (q)-[:AMENDS]->(t)
               MERGE (q)-[:ABOUT]->(f)""", {"cs": changes})
    g.query("""UNWIND $cs AS c WITH c WHERE c.decision
               MATCH (m:Message {id: c.msg}), (q:Requirement {id: c.id}), (p:Person {id: c.author})
               MERGE (d:Decision {id: 'dec:' + c.msg})
               SET d.text = c.text, d.at_ms = c.at_ms, d.at = c.at, d.origin = 'extractor'
               MERGE (p)-[:MADE]->(d)
               MERGE (d)-[:RECORDED_IN]->(m)
               MERGE (d)-[:CHANGES]->(q)""", {"cs": changes})
    log(f"requirement changes from chat: {len(changes)} ({', '.join(c['msg'] for c in changes)})")

    # 6. SUPERSEDES chains per ticket ----------------------------------------------
    reqs_by_ticket = defaultdict(list)
    for r in _rows_paged(g, """MATCH (q:Requirement) RETURN q.id AS id, q.ticket AS ticket, q.text AS text, q.origin AS origin,
                                                       q.at AS at, q.at_ms AS at_ms, q.confidence AS confidence
                                ORDER BY at_ms, id"""):
        reqs_by_ticket[r["ticket"]].append(r)
    pairs = [] if "supersession" in ablate else [
        p for chain in reqs_by_ticket.values() for p in supersession_pairs(chain, ex.reflects, (lambda n, o: True) if latest_wins else ex.replaces)]
    g.query("""UNWIND $ps AS p MATCH (n:Requirement {id: p.new}), (o:Requirement {id: p.old})
               MERGE (n)-[:SUPERSEDES]->(o)""", {"ps": pairs})

    # 7. IMPLEMENTS: which requirement version each PR actually delivers ----------
    impl = []
    for pr in prs:
        tickets_for_pr = [t for t, _, _ in pr_links.get(pr["id"], [])]
        cutoff = pr["merged_ms"] or pr["created_ms"]
        cands = [r for t in tickets_for_pr for r in reqs_by_ticket[t] if r["at_ms"] <= cutoff]
        if cands and "supersession" not in ablate:
            impl += [{"pr": pr["id"], "r": rid} for rid in ex.implements(pr, cands)]
    g.query("""UNWIND $xs AS x MATCH (pr:PullRequest {id: x.pr}), (q:Requirement {id: x.r})
               MERGE (pr)-[:IMPLEMENTS]->(q)""", {"xs": impl})
    log(f"IMPLEMENTS edges: {len(impl)}")

    # 8. Human actions (dismissals, write-backs) re-attached by stable id ------------
    from pipeline.human import relink
    relink(g)

    return {"features": features, "msg_feature": msg_feature, "pr_links": pr_links,
            "classification": cls, "changes": changes, "implements": impl}
