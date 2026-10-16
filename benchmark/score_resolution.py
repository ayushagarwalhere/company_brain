"""Scores the built graph against data/scenario/answer_key.json.

    python -m benchmark.score_resolution            # after `python -m pipeline.build`

Reports precision / recall for: message->feature links, PR->ticket links,
requirement-change detection, and drift detection.
"""
import json
from pathlib import Path

from graph.db import get_graph
from graph.queries import drift, rows

KEY = json.loads((Path(__file__).resolve().parent.parent / "data" / "scenario" / "answer_key.json").read_text(encoding="utf-8"))


def prf(pred: set, gold: set) -> dict:
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 1.0
    r = tp / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp,
            "fp": sorted(pred - gold), "fn": sorted(gold - pred)}


def feature_map(g) -> dict[str, str]:
    """Map predicted feature ids to answer-key ids by best ticket overlap."""
    pred = {}
    for r in rows(g, "MATCH (t:Ticket)-[:ABOUT]->(f:Feature) RETURN f.id AS f, collect(t.id) AS ts"):
        best = max(KEY["features"], key=lambda k: len(set(k["tickets"]) & set(r["ts"])))
        if set(best["tickets"]) & set(r["ts"]):
            pred[r["f"]] = best["id"]
    return pred


def score(g) -> dict:
    fmap = feature_map(g)
    out = {}

    gold_tf = {(t, f["id"]) for f in KEY["features"] for t in f["tickets"]}
    pred_tf = {(r["t"], fmap.get(r["f"], r["f"])) for r in rows(g, "MATCH (t:Ticket)-[:ABOUT]->(f:Feature) RETURN t.id AS t, f.id AS f")}
    out["ticket_to_feature"] = prf(pred_tf, gold_tf)

    gold_mf = {(m, f) for f, ms in KEY["message_links"].items() for m in ms}
    pred_mf = {(r["m"], fmap.get(r["f"], r["f"])) for r in rows(g, "MATCH (m:Message)-[:ABOUT]->(f:Feature) RETURN m.id AS m, f.id AS f")}
    out["message_to_feature"] = prf(pred_mf, gold_mf)

    gold_pr = {(f"PR-{p['pr']}", p["ticket"]) for p in KEY["pr_links"] if p["ticket"]}
    pred_pr = {(r["pr"], r["t"]) for r in rows(g, "MATCH (pr:PullRequest)-[:REFERENCES]->(t:Ticket) RETURN pr.id AS pr, t.id AS t")}
    out["pr_to_ticket"] = prf(pred_pr, gold_pr)

    gold_ch = {d["message"] for d in KEY["decisions"]}
    pred_ch = {r["m"] for r in rows(g, "MATCH (m:Message)-[:CHANGES]->(:Requirement) RETURN m.id AS m")}
    out["requirement_changes"] = prf(pred_ch, gold_ch)

    gold_dr = {(d["feature"], d["ticket"]) for d in KEY["expected_drift"]}
    found = drift(g)
    pred_dr = {(fmap.get(d["feature"], d["feature"]), d["ticket"]) for d in found}
    out["drift"] = prf(pred_dr, gold_dr)
    # per requirement: which chat messages' changes are flagged (catches false alarms that land on an already-drifted ticket)
    origin_msg = {r["id"]: r["origin"]["id"] for r in KEY["requirements"] if r["origin"]["kind"] == "message"}
    gold_req = {origin_msg[d["requirement"]] for d in KEY["expected_drift"]}
    pred_req = {d["message"] for d in found}
    out["drift_requirements"] = prf(pred_req, gold_req)
    gold_stale = {(d["ticket"], n) for d in KEY["expected_drift"] for n in d["stale_prs"]}
    pred_stale = {(d["ticket"], p["pr"]) for d in found for p in d["stale_prs"] if p["pr"] is not None}
    out["drift_stale_prs"] = prf(pred_stale, gold_stale)
    gold_docs = {(d["ticket"], x) for d in KEY["expected_drift"] for x in d.get("stale_docs", [])}
    pred_docs = {(d["ticket"], x["id"]) for d in found for x in d["stale_docs"]}
    out["drift_stale_docs"] = prf(pred_docs, gold_docs)
    return out


def print_report(out: dict) -> None:
    for name, s in out.items():
        print(f"{name:22s} P={s['precision']:.2f} R={s['recall']:.2f} F1={s['f1']:.2f}"
              + (f"  FP={s['fp'][:6]}" if s["fp"] else "") + (f"  FN={s['fn'][:6]}" if s["fn"] else ""))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", help="score a graph other than the default (e.g. one built with --graph llm_demo)")
    ap.add_argument("--json", help="also write the scores to this file")
    a = ap.parse_args()
    out = score(get_graph(a.graph))
    print_report(out)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
