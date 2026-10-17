"""Container entrypoint: wait for FalkorDB, build the graph if it's empty, start the API.

EXTRACTOR=heuristic|deepseek|oracle overrides the automatic choice (Render uses heuristic
so the free instance boots in seconds instead of making ~300 LLM calls first).

    python -m scripts.serve

Extraction uses the configured LLM when one answers, otherwise the rule-based heuristic
extractor; the dashboard says which one built the graph.
"""

import os
import time

import uvicorn

from config import settings
from graph.db import get_db, get_graph


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
    from pipeline import llm
    from pipeline.build import build_graph

    # an LLM only when one actually answers; the committed cache holds qwen3 answers, so it can't stand in for DeepSeek
    extractor = os.getenv("EXTRACTOR") or ("llm" if llm.available() else "heuristic")
    print(f"building graph with {extractor} extraction ...")
    build_graph(extractor=extractor)


if __name__ == "__main__":
    wait_for_db()
    ensure_graph()
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
