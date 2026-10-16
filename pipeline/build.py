"""Full build: ingest -> resolve -> report drift.

    python -m pipeline.build                        # DeepSeek if it answers, else heuristic
    python -m pipeline.build --extractor heuristic  # rule-based extraction, no LLM
    python -m pipeline.build --extractor oracle     # answer-key extraction (tests resolution + drift only)
"""
import argparse
from datetime import datetime, timezone

from graph.db import get_graph
from graph.queries import drift
from pipeline.ingest import ingest
from pipeline.resolve import resolve


def mark_build(g, extractor: str) -> None:
    """Records how the graph was built, so the dashboard can say whether extraction was an LLM (and which), rules or the oracle."""
    from pipeline.llm import model_name
    extractor = "llm" if extractor == "deepseek" else extractor
    g.query("MERGE (b:Build {id: 'latest'}) SET b.extractor = $e, b.model = $m, b.at = $at",
            {"e": extractor, "m": model_name() if extractor == "llm" else None,
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def build_graph(graph: str | None = None, extractor: str = "heuristic", semantic: str | None = None,
                live: bool = False, log=print):
    """What `python -m pipeline.build` does: ingest from source, resolve, record the build.
    Human actions (dismissals, write-backs) are not in the sources, so they are carried across the wipe."""
    from pipeline import human
    kept = human.snapshot(get_graph(graph))
    log(ingest(live=live, reset=True, graph_name=graph))
    g = get_graph(graph)
    human.restore(g, kept)
    resolve(g, extractor, semantic, log=log)
    mark_build(g, extractor)
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", default="auto", choices=["auto", "llm", "deepseek", "heuristic", "oracle"],
                    help="auto = llm if the configured LLM answers, else heuristic ('deepseek' = 'llm')")
    ap.add_argument("--semantic", choices=["llm", "tfidf"])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--graph")
    a = ap.parse_args()

    if a.extractor == "auto":
        from pipeline import llm
        a.extractor = "llm" if llm.available() else "heuristic"
        if a.extractor == "heuristic":
            print(f"LLM unavailable ({llm.unavailable_reason()}): using the heuristic extractor")
    g = build_graph(a.graph, a.extractor, a.semantic, a.live)
    print("\nDRIFT")
    for d in drift(g):
        prs = ", ".join(f"#{p['pr']}" for p in d["stale_prs"] if p["pr"] is not None) or "none"
        print(f"- {d['feature']} / {d['ticket']}: \"{d['requirement_text']}\"\n"
              f"    changed by {d['changed_by']} in {d['source']}#{d['channel']} ({d['message']}, {d['changed_at']})\n"
              f"    ticket still says: {d['ticket_text']}\n    stale PRs: {prs}")


if __name__ == "__main__":
    main()
