"""Graph vs. retrieval at stress-test scale (200 features, 20,800 messages), rules agent, no LLM.

    python -m benchmark.qa_scale        # -> benchmark/results/qa_scale.json

The demo Q&A benchmark is too small to separate the two (25 passages cover almost everything).
This one asks two kinds of questions over the generated org of benchmark/scale.py:

  per-feature   "What is the current requirement for the <topic> report?", "Which PR shipped the old
                version of ...?". Each topic word is unique and the 20k noise messages are generic
                chatter, so retrieval should find these easily. Graded by required facts (benchmark/run.py).
  cross-feature "Which tickets are stale compared with what was decided in chat?" and similar: the
                answer is 100 tickets/PRs spread over 200 features. Graded by F1 over the ticket or PR
                ids named in the answer.

Questions are generated from the generator's ground truth with a fixed seed, written before any run
(one was removed after the first run, see questions()).

Known artifact: drifted tickets have one version in their history and clean ones two, so drifted tickets'
passages are shorter and TF-IDF ranks them first. Retrieval's score on "which tickets are stale" partly
reflects that, not understanding. Reported, not corrected.
The graph side is the rules agent (agent/router.py); retrieval is extractive TF-IDF top-25 and top-100.
"""
import json
import random
import re
import time

from benchmark.run import HERE, grade
from benchmark.scale import synth
from pipeline.textsim import TfIdf

ORG = "scaleqa"
SEED = 0


def build():
    from graph import writer
    from graph.db import get_graph, org_graph_name, set_org
    from pipeline.resolve import resolve
    people, msgs, tickets, prs, expected = synth(200, 20000)
    name = org_graph_name(ORG)
    try:
        get_graph(name).delete()
    except Exception:  # noqa: BLE001 - graph didn't exist
        pass
    g = get_graph(name)
    writer.apply_schema(g)
    writer.write_people(g, [{"id": p, "name": p, "role": "engineer"} for p in people])
    writer.write_tickets(g, tickets)
    writer.write_messages(g, msgs)
    writer.write_pull_requests(g, prs)
    resolve(g, "heuristic", log=lambda *_: None)
    set_org(ORG)  # the agent's tools now read this graph
    return msgs, tickets, prs, expected


def corpus(msgs, tickets, prs) -> dict[str, str]:
    docs = {m.id: f"[{m.ts} {m.source}#{m.channel}] {m.author}: {m.text}" for m in msgs}
    for t in tickets:
        hist = " | ".join(f"{v['at']}: {v['to']}" for v in t.extra["versions"])
        docs[t.id] = f"[ticket {t.id}, assignee {t.extra['assignee']}] {t.extra['title']}: {t.extra['description']} (history: {hist})"
    for p in prs:
        docs[p.id] = f"[PR #{p.extra['number']} by {p.author}, merged {p.extra['merged_at']}] {p.text}"
    return docs


def questions(tickets, expected) -> list[dict]:
    """Per-feature questions for 6 drifted and 6 clean features, plus 4 cross-feature questions."""
    from benchmark.scale import WORDS
    rng = random.Random(SEED)
    feats = [f for f in range(200)]
    drifted = [f for f in feats if f"SC-{f * 3}" in expected]
    clean = [f for f in feats if f"SC-{f * 3}" not in expected]
    qs = []
    for f in rng.sample(drifted, 6) + rng.sample(clean, 6):
        topic, new_n = f"{WORDS[f % len(WORDS)]}{f}", 100 + f
        qs.append({"id": f"cur_{f}", "kind": "per-feature", "q": f"What is the current requirement for the {topic} report?",
                   "must": [[str(new_n)]]})
        if f in drifted:
            qs.append({"id": f"pr_{f}", "kind": "per-feature", "q": f"Which PR shipped the old version of the {topic} report requirement?",
                       "must": [[f"#{f + 1}", f"PR-{f + 1}", f"PR #{f + 1}"]]})
    stale_tickets = sorted(expected)
    stale_prs = sorted(f"#{int(t.split('-')[1]) // 3 + 1}" for t in expected)
    qs += [
        {"id": "x_stale_tickets", "kind": "cross-feature", "q": "Which tickets are stale compared with what was decided in chat?",
         "ids": stale_tickets, "pattern": r"SC-\d+"},
        {"id": "x_drift_features", "kind": "cross-feature", "q": "Which features have requirement drift?",
         "ids": stale_tickets, "pattern": r"SC-\d+"},
        {"id": "x_stale_prs", "kind": "cross-feature", "q": "Which pull requests shipped a requirement that was later changed in chat?",
         "ids": stale_prs, "pattern": r"#\d+"},
        # Removed after the first run: "How many features have open drift?" (expected "100") was answered by
        # EVERY system, because feature 0's requirement is literally "the last 100 entries". Broken question.
    ]
    return qs


def grade_q(answer: str, q: dict) -> float:
    if "ids" in q:
        named = set(re.findall(q["pattern"], answer or ""))
        if q["pattern"] == r"SC-\d+":
            named = {x for x in named if int(x.split("-")[1]) % 3 == 0}  # main tickets only; siblings never drift
        gold = set(q["ids"])
        tp = len(named & gold)
        if not tp:
            return 0.0
        p, r = tp / len(named), tp / len(gold)
        return round(2 * p * r / (p + r), 3)
    return grade(answer, q)["score"]


def main():
    from agent.router import ask
    t = time.time()
    msgs, tickets, prs, expected = build()
    built_s = round(time.time() - t, 1)
    docs = corpus(msgs, tickets, prs)
    index = TfIdf(docs)

    def extractive(q, k):
        ranked = sorted(index.scores(q).items(), key=lambda kv: -kv[1])[:k]
        return "\n".join(docs[d] for d, _ in ranked)

    systems = {"graph (rules agent, no LLM)": lambda q: ask(q)["answer"],
               "retrieval top-25 (extractive, no LLM)": lambda q: extractive(q, 25),
               "retrieval top-100 (extractive, no LLM)": lambda q: extractive(q, 100)}
    qs = questions(tickets, expected)
    results = {s: [] for s in systems}
    for q in qs:
        for s, fn in systems.items():
            answer = fn(q["q"])
            results[s].append({"id": q["id"], "kind": q["kind"], "q": q["q"], "score": grade_q(answer, q),
                               "chars": len(answer), "answer_head": answer[:400]})
    summary = {}
    for s, rs in results.items():
        summary[s] = {kind: {"questions": len(x), "mean_score": round(sum(r["score"] for r in x) / len(x), 3),
                             "fully_correct": sum(r["score"] == 1.0 for r in x)}
                      for kind in ("per-feature", "cross-feature") for x in [[r for r in rs if r["kind"] == kind]]}
        summary[s]["mean_answer_chars"] = round(sum(r["chars"] for r in rs) / len(rs))
    out = {"org": {"features": 200, "messages": len(msgs), "tickets": len(tickets), "prs": len(prs),
                   "drifted_features": len(expected), "build_s": built_s},
           "grader": "per-feature: required facts; cross-feature: F1 over ticket/PR ids named", "seed": SEED,
           "summary": summary, "results": results}
    (HERE / "results" / "qa_scale.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    for i, q in enumerate(qs):
        print(q["id"].ljust(18), "  ".join(f"{results[s][i]['score']:.2f}" for s in systems))


if __name__ == "__main__":
    main()
