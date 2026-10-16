"""Shows FalkorDB execution plans (GRAPH.EXPLAIN) for the product's hot queries and checks index use.

    python -m scripts.explain_queries          # prints each plan; exits 1 if a lookup falls back to a label scan
"""
import sys

from graph import queries as Q
from graph.db import get_graph

# (name, query, params, must use an index?)
CHECKS = [
    ("ticket by id", "MATCH (t:Ticket {id: $t}) RETURN t.title", {"t": "BD-101"}, True),
    ("requirements of a ticket", "MATCH (q:Requirement {ticket: $t}) RETURN q.id ORDER BY q.at_ms", {"t": "BD-101"}, True),
    ("messages since a time", "MATCH (m:Message) WHERE m.ts_ms > $t RETURN count(m)", {"t": 0}, True),
    ("PR by number", "MATCH (pr:PullRequest {number: $n}) RETURN pr.id", {"n": 6}, True),
    ("drift (core query)", Q.DRIFT, {"feature": None, "ticket": None}, False),
    ("drift for one ticket", Q.DRIFT_FOR_TICKET, {"feature": None, "ticket": "BD-101"}, True),
    ("connection (liam -> PR-6)", Q.CONNECTION.replace("__LA__", "Person").replace("__LB__", "PullRequest"), {"a": "liam", "b": "PR-6"}, True),
    ("neighbours of a ticket", "MATCH (n:Ticket {id: $id})-[r]-(m) RETURN m.id LIMIT 40", {"id": "BD-101"}, True),
]


def main() -> int:
    g = get_graph()
    bad = 0
    for name, q, params, need_index in CHECKS:
        plan = str(g.explain(q, params))
        uses = "Index Scan" in plan or "Index Seek" in plan
        status = "index" if uses else "scan"
        flag = "" if (uses or not need_index) else "   <-- expected an index"
        bad += bool(flag)
        print(f"\n== {name}: {status}{flag}")
        print("\n".join("   " + line for line in plan.splitlines()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
