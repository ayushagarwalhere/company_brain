"""Graph vs. a relational baseline over the SAME extracted facts.

    python -m benchmark.sql_baseline        # -> benchmark/results/sql_baseline.json

resolve() is run once per dataset (it is the shared extraction step). Its plain-data output (requirements,
chat changes, PR->ticket links, IMPLEMENTS judgments, and the supersession pairs computed in Python) is
loaded into an in-memory SQLite database. No graph query is used on the SQL side. Two SQL variants:

  sql_latest  "current requirement" = newest requirement per ticket (ROW_NUMBER window). No version chain.
  sql_chain   given the same SUPERSEDES pairs the graph receives, drift is an anti-join.

Both are compared with the graph's DRIFT query on: drift found (vs. gold), stale PRs, the current
requirement per ticket, p50 query time, and lines of query code.
"""
import json
import sqlite3
import statistics
import time

from benchmark.run import HERE
from graph import queries as Q
from graph.db import get_graph

SCHEMA = """
CREATE TABLE requirement (id TEXT PRIMARY KEY, ticket TEXT, origin TEXT, at_ms INTEGER, text TEXT);
CREATE TABLE change (req TEXT PRIMARY KEY, msg TEXT, author TEXT);
CREATE TABLE ticket_feature (ticket TEXT PRIMARY KEY, feature TEXT);
CREATE TABLE pr (id TEXT PRIMARY KEY, number INTEGER, merged_ms INTEGER);
CREATE TABLE pr_ticket (pr TEXT, ticket TEXT);
CREATE TABLE implements (pr TEXT, req TEXT);
CREATE TABLE supersedes (new TEXT, old TEXT);
CREATE TABLE dismissed (req TEXT PRIMARY KEY);
CREATE INDEX req_ticket ON requirement (ticket, at_ms);
CREATE INDEX sup_old ON supersedes (old);
CREATE INDEX impl_req ON implements (req);
CREATE INDEX prt_ticket ON pr_ticket (ticket);
"""

# drift with the same version chain the graph uses: newest-by-chain, unimplemented, undismissed chat requirement
SQL_CHAIN = """
SELECT r.id, r.ticket FROM requirement r
JOIN change c ON c.req = r.id
JOIN ticket_feature tf ON tf.ticket = r.ticket
WHERE NOT EXISTS (SELECT 1 FROM supersedes s WHERE s.old = r.id)
  AND NOT EXISTS (SELECT 1 FROM implements i WHERE i.req = r.id)
  AND NOT EXISTS (SELECT 1 FROM dismissed d WHERE d.req = r.id)
"""

# drift without a version chain: the newest requirement on the ticket is a chat one nobody implemented
SQL_LATEST = """
WITH ranked AS (
  SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.ticket ORDER BY r.at_ms DESC, r.id DESC) AS rn FROM requirement r)
SELECT r.id, r.ticket FROM ranked r
JOIN change c ON c.req = r.id
JOIN ticket_feature tf ON tf.ticket = r.ticket
WHERE r.rn = 1
  AND NOT EXISTS (SELECT 1 FROM implements i WHERE i.req = r.id)
  AND NOT EXISTS (SELECT 1 FROM dismissed d WHERE d.req = r.id)
"""

SQL_STALE = """
WITH drift AS ({drift})
SELECT d.id, p.number FROM drift d JOIN pr_ticket pt ON pt.ticket = d.ticket JOIN pr p ON p.id = pt.pr
"""

SQL_CURRENT_CHAIN = "SELECT r.ticket, r.id FROM requirement r WHERE NOT EXISTS (SELECT 1 FROM supersedes s WHERE s.old = r.id)"
GRAPH_CURRENT = "MATCH (q:Requirement) WHERE q.status IS NULL AND NOT (q)<-[:SUPERSEDES]-(:Requirement) RETURN q.ticket AS ticket, q.id AS id"


def load(out: dict, dismissed=()) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO requirement VALUES (?,?,?,?,?)",
                   [(r["id"], r["ticket"], r["origin"], r["at_ms"], r["text"]) for r in out["requirements"]])
    db.executemany("INSERT OR IGNORE INTO change VALUES (?,?,?)", [(c["id"], c["msg"], c["author"]) for c in out["changes"]])
    db.executemany("INSERT INTO ticket_feature VALUES (?,?)", list(out["ticket_feature"].items()))
    db.executemany("INSERT INTO pr VALUES (?,?,?)", [(p["id"], p["number"], p["merged_ms"]) for p in out["prs"]])
    db.executemany("INSERT INTO pr_ticket VALUES (?,?)", [(p, t) for p, ls in out["pr_links"].items() for t, _, _ in ls])
    db.executemany("INSERT INTO implements VALUES (?,?)", [(x["pr"], x["r"]) for x in out["implements"]])
    db.executemany("INSERT INTO supersedes VALUES (?,?)", [(x["new"], x["old"]) for x in out["supersedes"]])
    db.executemany("INSERT INTO dismissed VALUES (?)", [(r,) for r in dismissed])
    return db


def p50(fn, n=20) -> float:
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(xs), 2)


def lines(q: str) -> int:
    return sum(1 for line in q.strip().splitlines() if line.strip())


def compare(name: str, g, out: dict, gold_reqs: set | None = None, gold_tickets: set | None = None) -> dict:
    db = load(out)
    graph_drift = {(d["requirement"], d["ticket"]) for d in Q.drift(g)}
    variants = {"graph": graph_drift,
                "sql_chain": set(map(tuple, db.execute(SQL_CHAIN).fetchall())),
                "sql_latest": set(map(tuple, db.execute(SQL_LATEST).fetchall()))}
    graph_stale = {(d["requirement"], p["pr"]) for d in Q.drift(g) for p in d["stale_prs"] if p["pr"] is not None}
    stale = {"graph": graph_stale,
             "sql_chain": set(map(tuple, db.execute(SQL_STALE.format(drift=SQL_CHAIN)).fetchall())),
             "sql_latest": set(map(tuple, db.execute(SQL_STALE.format(drift=SQL_LATEST)).fetchall()))}
    current_graph = {(r[0], r[1]) for r in g.query(GRAPH_CURRENT).result_set}
    current_sql = set(map(tuple, db.execute(SQL_CURRENT_CHAIN).fetchall()))

    def score(found):
        if gold_reqs is not None:
            got = {r for r, _ in found}
            tp = len(got & gold_reqs)
            return {"found": len(got), "true": tp, "false": len(got - gold_reqs), "missed": len(gold_reqs - got)}
        got = {t for _, t in found}
        tp = len(got & gold_tickets)
        return {"found": len(got), "true": tp, "false": len(got - gold_tickets), "missed": len(gold_tickets - got)}

    res = {"dataset": name, "requirements": len(out["requirements"]), "chat_changes": len(out["changes"]),
           "drift": {k: score(v) for k, v in variants.items()},
           "same_drift_as_graph": {k: v == graph_drift for k, v in variants.items() if k != "graph"},
           "same_stale_prs_as_graph": {k: v == graph_stale for k, v in stale.items() if k != "graph"},
           "same_current_requirements_as_graph": current_sql == current_graph,
           "p50_ms": {"graph": p50(lambda: Q.drift(g)), "sql_chain": p50(lambda: db.execute(SQL_CHAIN).fetchall()),
                      "sql_latest": p50(lambda: db.execute(SQL_LATEST).fetchall())}}
    return res


def demo():
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    name = "sqlbase_demo"
    ingest(reset=True, graph_name=name)
    g = get_graph(name)
    out = resolve(g, "heuristic", log=lambda *_: None)
    try:
        return compare("demo (300 messages)", g, out, gold_reqs={"req:m_exp_12", "req:m_sla_05"})
    finally:
        g.delete()


def noise():
    from benchmark.noise import noise_messages
    from graph import writer
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    name = "sqlbase_noise"
    ingest(reset=True, graph_name=name)
    g = get_graph(name)
    writer.write_messages(g, noise_messages())
    out = resolve(g, "heuristic", log=lambda *_: None)
    try:
        return compare("demo + 500 noise messages", g, out, gold_reqs={"req:m_exp_12", "req:m_sla_05"})
    finally:
        g.delete()


def scale():
    from benchmark.scale import synth
    from graph import writer
    from pipeline.resolve import resolve
    people, msgs, tickets, prs, expected = synth(200, 20000)
    name = "sqlbase_scale"
    g = get_graph(name)
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass
    g = get_graph(name)
    writer.apply_schema(g)
    writer.write_people(g, [{"id": p, "name": p, "role": "engineer"} for p in people])
    writer.write_tickets(g, tickets)
    writer.write_messages(g, msgs)
    writer.write_pull_requests(g, prs)
    out = resolve(g, "heuristic", log=lambda *_: None)
    try:
        return compare("stress test (20,800 messages)", g, out, gold_tickets=set(expected))
    finally:
        g.delete()


def main():
    results = [demo(), noise(), scale()]
    code = {"graph DRIFT (Cypher)": lines(Q.DRIFT), "sql_chain drift": lines(SQL_CHAIN), "sql_latest drift": lines(SQL_LATEST),
            "graph current requirement": lines(GRAPH_CURRENT), "sql current requirement": lines(SQL_CURRENT_CHAIN)}
    out = {"note": "same extracted facts on both sides; the SQL side never reads the graph", "lines_of_query_code": code, "results": results}
    (HERE / "results" / "sql_baseline.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
