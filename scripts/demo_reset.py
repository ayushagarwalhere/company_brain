"""Put the demo back in its starting state and check it before recording or presenting.

    python -m scripts.demo_reset                       # rebuild the graph directly (extractor: auto)
    python -m scripts.demo_reset --api http://localhost:8000   # ask the running server to rebuild
    python -m scripts.demo_reset --extractor heuristic          # force the no-LLM path

Going through --api also clears the server's in-memory alert cooldown, so the same live message
can be posted again within 5 minutes. Either way, open dashboards get a "rebuild" event.
Exits 1 if the planted state isn't there (drift on exactly BD-101 and BD-103).
"""

import argparse
import json
import sys

EXPECTED_DRIFT = {"BD-101", "BD-103"}


def rebuild(extractor: str = "auto", graph: str | None = None) -> str:
    from api import bus
    from graph.db import get_graph
    from pipeline import llm
    from pipeline.build import mark_build
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    if extractor == "auto":
        extractor = "llm" if llm.available() else "heuristic"
    ingest(reset=True, graph_name=graph)
    g = get_graph(graph)
    resolve(g, extractor, log=lambda *_: None)
    mark_build(g, extractor)
    bus.publish("rebuild", extractor=extractor)
    return extractor


def check(graph: str | None = None) -> dict:
    from graph.db import get_graph
    from graph.queries import drift
    from pipeline import llm

    tickets = sorted({d["ticket"] for d in drift(get_graph(graph))})
    return {"drift_tickets": tickets, "ok": set(tickets) == EXPECTED_DRIFT, "llm": "online" if llm.available() else f"offline ({llm.unavailable_reason()})"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", help="base URL of a running server, e.g. http://localhost:8000")
    ap.add_argument("--extractor", default="auto", choices=["auto", "llm", "heuristic"])
    a = ap.parse_args(argv)
    if a.api:
        import os

        import requests

        headers = {"X-Ingest-Token": os.getenv("INGEST_TOKEN", "")} if os.getenv("INGEST_TOKEN") else {}
        r = requests.post(a.api.rstrip("/") + "/api/demo/reset", headers=headers, timeout=120)
        r.raise_for_status()
        used = r.json()["rebuilt_with"]
    else:
        used = rebuild(a.extractor)
    out = {"rebuilt_with": used, **check()}
    print(json.dumps(out, indent=1))
    if not out["ok"]:
        print(f"expected drift on {sorted(EXPECTED_DRIFT)}", file=sys.stderr)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
