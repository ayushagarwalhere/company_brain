"""Benchmark: the same questions answered WITH the graph and WITHOUT it.

  graph     the tool-calling agent over FalkorDB (agent/agent.py)
  baseline  no graph: TF-IDF retrieval over the same raw messages, tickets and PRs,
            top-K chunks pasted into DeepSeek (classic RAG). Same model, same data.

Scoring is deterministic: each question lists required facts (any synonym in a group
must appear) and optional forbidden claims. Results go to benchmark/results/.

    python -m benchmark.run                # both systems
    python -m benchmark.run --only graph
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from connectors import github, scenario, tickets
from pipeline.llm import chat_text
from pipeline.textsim import TfIdf

HERE = Path(__file__).resolve().parent
QUESTIONS = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
TOP_K = 25

BASELINE_SYSTEM = """You answer questions about a software team's decisions, tickets and pull requests using ONLY the documents given.
Be concise; name tickets (BD-...), PRs (#n), people and dates. If unsure, say so."""


def corpus() -> dict[str, str]:
    docs = {}
    for m in scenario.messages():
        docs[m.id] = f"[{m.ts} {m.source}#{m.channel}] {m.author}: {m.text}"
    for t in tickets.tickets():
        x = t.extra
        hist = " | ".join(f"{v['at']}: {v['to']}" for v in x["versions"])
        docs[t.id] = f"[ticket {t.id}, state {x['state']}, assignee {x['assignee']}, sprint {x['sprint']}] {x['title']}: {x['description']} (history: {hist})"
    for p in github.pull_requests_from_scenario():
        docs[p.id] = f"[PR #{p.extra['number']} by {p.author}, created {p.ts}, merged {p.extra['merged_at']}] {p.text}"
    return docs


def baseline_answer(q: str, index: TfIdf, docs: dict[str, str]) -> dict:
    ranked = sorted(index.scores(q).items(), key=lambda kv: -kv[1])[:TOP_K]
    context = "\n".join(docs[k] for k, _ in sorted(ranked, key=lambda kv: docs[kv[0]]))
    return {"answer": chat_text(BASELINE_SYSTEM, f"Documents:\n{context}\n\nQuestion: {q}", temperature=0), "retrieved": [k for k, _ in ranked]}


def graph_answer(q: str) -> dict:
    from agent.agent import ask
    return ask(q)


def grade(answer: str, item: dict) -> dict:
    a = (answer or "").lower()
    hits = [any(s.lower() in a for s in group) for group in item["must"]]
    bad = [any(s.lower() in a for s in group) for group in item.get("must_not", [])]
    score = sum(hits) / len(hits) if hits else 1.0
    if any(bad):
        score = 0.0
    return {"score": round(score, 3), "hits": hits, "forbidden": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["graph", "baseline"])
    a = ap.parse_args()
    systems = [a.only] if a.only else ["graph", "baseline"]
    docs = corpus()
    index = TfIdf(docs)
    results = {s: [] for s in systems}
    for item in QUESTIONS:
        for s in systems:
            t0 = time.time()
            out = graph_answer(item["q"]) if s == "graph" else baseline_answer(item["q"], index, docs)
            g = grade(out["answer"], item)
            results[s].append({"id": item["id"], "q": item["q"], "answer": out["answer"], **g,
                               "seconds": round(time.time() - t0, 1), "tools": out.get("tool_calls")})
            print(f"{item['id']} {s:8s} {g['score']:.2f}")
    summary = {s: round(sum(r["score"] for r in rs) / len(rs), 3) for s, rs in results.items()}
    print("\nmean score:", summary)
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"run_{stamp}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
