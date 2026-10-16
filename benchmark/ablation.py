"""Ablation study: does the graph do real work? Switch graph capabilities off one at a time
and measure what breaks against the answer key. Deterministic, no LLM, no API keys.

    python -m benchmark.ablation            # prints a Markdown table, saves benchmark/results/ablation.json

Each run uses the heuristic extractor on a throwaway graph, so the only thing that
changes between rows is which graph structure the resolver is allowed to use.
"""

import json
from pathlib import Path

from benchmark.score_resolution import score
from graph.db import get_graph
from pipeline.ingest import ingest
from pipeline.resolve import resolve

CONFIGS = [
    ("Full graph", frozenset()),
    ("− thread structure (REPLY_TO)", frozenset({"threads"})),
    ("− person/time proximity for PRs", frozenset({"pr_proximity"})),
    ("− version reasoning (SUPERSEDES / IMPLEMENTS)", frozenset({"supersession"})),
    ("− time-aware IMPLEMENTS fallback", frozenset({"implements_fallback"})),
    ("Ticket IDs only (no threads, proximity or semantic)", frozenset({"threads", "pr_proximity", "semantic"})),
]
METRICS = [
    ("message_to_feature", "Msg→feature"),
    ("pr_to_ticket", "PR→ticket"),
    ("requirement_changes", "Changes"),
    ("drift", "Drift (ticket)"),
    ("drift_requirements", "Drift (requirement)"),
    ("drift_stale_prs", "Stale PRs"),
]
GRAPH = "ablation_tmp"


def run() -> list[dict]:
    rows = []
    for name, ablate in CONFIGS:
        ingest(reset=True, graph_name=GRAPH)
        g = get_graph(GRAPH)
        try:
            resolve(g, "heuristic", log=lambda *_: None, ablate=ablate)
            s = score(g)
        finally:
            g.delete()
        rows.append({"config": name, "ablate": sorted(ablate), "scores": s})
    return rows


def table(rows: list[dict]) -> str:
    fmt = lambda m: f"{m['precision']:.2f} / {m['recall']:.2f}"  # noqa: E731
    out = ["| Configuration | " + " | ".join(label + " P / R" for _, label in METRICS) + " |", "|---|" + "---|" * len(METRICS)]
    for r in rows:
        out.append(f"| {r['config']} | " + " | ".join(fmt(r["scores"][k]) for k, _ in METRICS) + " |")
    return "\n".join(out)


def what_broke(rows: list[dict]) -> list[str]:
    base = rows[0]["scores"]
    notes = []
    for r in rows[1:]:
        lost = []
        for k, label in METRICS:
            s = r["scores"][k]
            extra_fp = [x for x in s["fp"] if x not in base[k]["fp"]]
            extra_fn = [x for x in s["fn"] if x not in base[k]["fn"]]
            if extra_fp:
                lost.append(f"{label}: false positives {extra_fp[:4]}")
            if extra_fn:
                lost.append(f"{label}: missed {extra_fn[:4]}")
        notes.append(f"- **{r['config']}**: " + ("; ".join(lost) if lost else "no change on this dataset"))
    return notes


def check(rows: list[dict]) -> list[str]:
    """Regression guards, run in CI: the full graph must find exactly the planted drift, and removing version
    reasoning must make drift worse. Returns the failures (empty = pass)."""
    by = {r["config"]: r["scores"] for r in rows}
    full = by["Full graph"]
    fails = []
    for k in ("drift", "drift_requirements"):
        if (full[k]["precision"], full[k]["recall"]) != (1.0, 1.0):
            fails.append(f"full graph {k}: P={full[k]['precision']} R={full[k]['recall']}, expected 1.00 / 1.00")
    nov = by["− version reasoning (SUPERSEDES / IMPLEMENTS)"]
    worse = any(nov[k]["precision"] < full[k]["precision"] or nov[k]["recall"] < full[k]["recall"] for k in ("drift", "drift_requirements"))
    if not worse:
        fails.append("removing version reasoning no longer makes drift worse: the ablation would not show what the graph adds")
    return fails


if __name__ == "__main__":
    import sys

    rows = run()
    print(table(rows))
    print()
    print("\n".join(what_broke(rows)))
    out = Path(__file__).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    (out / "ablation.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    failures = check(rows)
    print()
    if failures:
        print("ABLATION CHECK FAILED:\n" + "\n".join(f"- {f}" for f in failures))
        sys.exit(1)
    print("ablation check passed: full graph drift P/R 1.00, and removing version reasoning makes drift worse")
