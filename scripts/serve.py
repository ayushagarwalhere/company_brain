"""Container entrypoint: wait for FalkorDB, build the graph if it's empty, start the API.

    python -m scripts.serve

Extraction uses DeepSeek when DEEPSEEK_API_KEY is set. Cached LLM results in
data/llm_cache/ are reused, so a committed cache reproduces the published run
without a key. With neither, it falls back to the rule-based heuristic extractor,
and the dashboard says which one built the graph.
"""
import os
import time

import uvicorn

from config import settings
from graph.db import get_db, get_graph
from pipeline.llm import CACHE_DIR


def wait_for_db(timeout: int = 60):
    t0 = time.time()
    while True:
        try:
            get_db().list_graphs()
            return
        except Exception:  # noqa: BLE001
            if time.time() - t0 > timeout:
                raise
            time.sleep(2)


def ensure_graph():
    g = get_graph()
    try:
        n = g.query("MATCH (f:Feature) RETURN count(f)").result_set[0][0]
    except Exception:  # noqa: BLE001 - graph doesn't exist yet
        n = 0
    if n and not os.getenv("REBUILD"):
        print(f"graph '{settings.falkordb_graph}' already built")
        return
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    has_cache = CACHE_DIR.exists() and any(CACHE_DIR.glob("*.json"))
    extractor = "deepseek" if (settings.deepseek_api_key or has_cache) else "heuristic"
    print(f"building graph with {extractor} extraction ...")
    ingest(reset=True)
    resolve(get_graph(), extractor)
    from pipeline.build import mark_build
    mark_build(get_graph(), extractor)


if __name__ == "__main__":
    wait_for_db()
    ensure_graph()
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
