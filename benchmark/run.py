"""Benchmark: the same questions answered WITH the graph and WITHOUT it.

  graph     the tool-calling agent over FalkorDB (agent/agent.py)
  baseline  no graph: TF-IDF retrieval over the same raw messages, tickets and PRs,
            top-K chunks pasted into DeepSeek (classic RAG). Same model, same data.

Scoring is deterministic: each question lists required facts (any synonym in a group
must appear) and optional forbidden claims. Results go to benchmark/results/.

    python -m benchmark.run                # LLM mode if DeepSeek answers, otherwise --no-llm
    python -m benchmark.run --no-llm       # rules agent vs. extractive retrieval (k=3 and k=25)

Two modes, never mixed in one result file:
  llm     graph = DeepSeek tool-calling agent; baseline = TF-IDF top-25 -> DeepSeek (classic RAG)
  no-llm  graph = rules agent (agent/router.py) over the same graph tools;
          baseline = extractive retrieval: the top-k TF-IDF passages ARE the answer (k=3 and k=25,
          both reported because k is arbitrary)
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


def graph_answer_rules(q: str) -> dict:
    from agent.router import ask
    return ask(q)


def baseline_extractive(q: str, index: TfIdf, docs: dict[str, str], k: int) -> dict:
    """No-LLM baseline: the k best-matching raw passages are returned verbatim as the answer."""
    ranked = sorted(index.scores(q).items(), key=lambda kv: -kv[1])[:k]
    return {"answer": "\n".join(docs[d] for d, _ in ranked), "retrieved": [d for d, _ in ranked]}


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
    ap.add_argument("--no-llm", action="store_true", help="rules agent vs. extractive retrieval")
    a = ap.parse_args()
    from pipeline import llm
    mode = "no-llm" if a.no_llm or not llm.available() else "llm"
    if mode == "no-llm" and not a.no_llm:
        print(f"LLM unavailable ({llm.unavailable_reason()}): running the no-LLM benchmark")
    docs = corpus()
    index = TfIdf(docs)
    if mode == "llm":
        from pipeline.llm import model_name
        systems = {f"graph (LLM agent, {model_name()})": graph_answer,
                   f"baseline (TF-IDF top-25 -> {model_name()})": lambda q: baseline_answer(q, index, docs)}
    else:
        systems = {"graph (rules agent, no LLM)": graph_answer_rules,
                   "baseline (extractive top-3, no LLM)": lambda q: baseline_extractive(q, index, docs, 3),
                   "baseline (extractive top-25, no LLM)": lambda q: baseline_extractive(q, index, docs, 25)}
    results = {s: [] for s in systems}
    for item in QUESTIONS:
        for s, fn in systems.items():
            t0 = time.time()
            out = fn(item["q"])
            g = grade(out["answer"], item)
            results[s].append({"id": item["id"], "q": item["q"], "answer": out["answer"], **g, "passed": g["score"] == 1.0,
                               "chars": len(out["answer"] or ""), "seconds": round(time.time() - t0, 2),
                               "tools": out.get("tool_calls")})
            print(f"{item['id']} {g['score']:.2f}  {s}")
    summary = {s: {"mean_score": round(sum(r["score"] for r in rs) / len(rs), 3),
                   "passed": sum(r["passed"] for r in rs), "questions": len(rs),
                   "mean_answer_chars": round(sum(r["chars"] for r in rs) / len(rs))} for s, rs in results.items()}
    print("\n" + json.dumps(summary, indent=1))
    payload = {"mode": mode, "grader": "keyword facts per question (benchmark/questions.json); lenient, see README",
               "summary": summary, "results": results}
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    from pipeline.llm import model_name
    payload["model"] = model_name() if mode == "llm" else None
    latest = "latest.json" if mode == "no-llm" else f"latest_llm_{model_name().replace(':', '-').replace('/', '-')}.json"
    for name in (f"run_{mode}_{stamp}.json", latest):
        (out_dir / name).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
