"""Scale test: a synthetic org much larger than the demo, with planted drifts at known positions.

    python -m benchmark.scale                          # 200 features, 20k noise messages
    python -m benchmark.scale --features 40 --noise 4000

Per feature: 3 tickets, a PR implementing the original requirement, a thread where a decision
changes it WITHOUT naming the ticket, and some replies. Half the features then get a ticket edit
that carries the decision (no drift); the other half don't (drift). Noise messages are mixed in.
Reports ingest, resolution and query latency, and checks drift is found exactly where planted.
Uses the heuristic extractor, so it runs without an LLM.
"""
import argparse
import json
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from graph import queries as Q
from graph import writer
from graph.db import get_graph
from pipeline.events import Event
from pipeline.resolve import resolve

GRAPH = "scale_test"
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
WORDS = ("alpha bravo cedar delta ember fable garnet harbor indigo juniper kestrel lumen meadow nimbus onyx prism quill "
         "raven sable tundra umber vertex willow xenon yarrow zephyr").split()


def synth(features: int, noise: int, seed: int = 7):
    rng = random.Random(seed)
    people = [f"p{i}" for i in range(40)]
    msgs, tickets, prs, expected = [], [], [], set()
    for f in range(features):
        topic = f"{WORDS[f % len(WORDS)]}{f}"
        start = T0 + timedelta(days=(f % 60))
        owner = people[f % len(people)]
        base_n, new_n = 10 + f % 7, 100 + f
        ids = [f"SC-{f * 3 + k}" for k in range(3)]
        main = ids[0]
        v1 = f"The {topic} report must include the last {base_n} entries for admins."
        versions = [{"at": iso(start), "to": v1, "actor": owner}]
        decision_at = start + timedelta(days=3)
        drift = f % 2 == 0
        if not drift:  # ticket edit that carries the decision, a day later
            versions.append({"at": iso(decision_at + timedelta(days=1)), "actor": owner,
                             "to": f"The {topic} report must include the last {new_n} entries for admins and managers."})
        else:
            expected.add(main)
        tickets.append(Event("tickets", "ticket", main, owner, iso(start), f"{topic} report\n\n{versions[-1]['to']}", extra={
            "title": f"{topic} report", "description": versions[-1]["to"], "state": "Done", "labels": [topic, "backend"],
            "assignee": owner, "sprint": None, "updated_at": versions[-1]["at"], "completed_at": iso(start + timedelta(days=5)),
            "versions": versions}))
        for k, extra_t in enumerate(ids[1:], 1):
            text = f"{topic} report {'export button' if k == 1 else 'performance tuning'}"
            tickets.append(Event("tickets", "ticket", extra_t, owner, iso(start), text, extra={
                "title": text, "description": f"Work on the {text}.", "state": "Done", "labels": [topic, "frontend"],
                "assignee": owner, "sprint": None, "updated_at": iso(start), "completed_at": None,
                "versions": [{"at": iso(start), "to": f"Work on the {text}.", "actor": owner}]}))
        root = f"s{f}_root"
        msgs.append(Event("slack", "message", root, people[(f + 1) % 40], iso(start + timedelta(days=2)),
                          f"Customers keep asking about the {topic} report, the last {base_n} entries is not enough.", channel="product"))
        msgs.append(Event("slack", "message", f"s{f}_dec", owner, iso(decision_at),
                          f"Decision: the {topic} report must include the last {new_n} entries, for admins and managers.",
                          channel="product", thread_of=root))
        msgs.append(Event("slack", "message", f"s{f}_ack", people[(f + 2) % 40], iso(decision_at + timedelta(minutes=5)),
                          "ok, will pass it on", channel="product", thread_of=root))
        msgs.append(Event("slack", "message", f"s{f}_id", owner, iso(start + timedelta(hours=2)),
                          f"Starting on {main} today.", channel="engineering"))
        prs.append(Event("github", "pull_request", f"PR-{f + 1}", owner, iso(start + timedelta(days=4)),
                         f"{main}: {topic} report\n\nFixes {main}. Shows the last {base_n} entries for admins.",
                         extra={"number": f + 1, "title": f"{main}: {topic} report", "body": f"Fixes {main}. Shows the last {base_n} entries for admins.",
                                "state": "merged", "merged_at": iso(start + timedelta(days=5))}))
    chatter = ["morning all", "lunch at 1?", "CI is green again.", "prod deploy done", "can someone review my PR, small one",
               "running late to standup", "rolling back the last deploy, seeing 500s", "fixed, it was a missing env var"]
    for i in range(noise):
        msgs.append(Event("slack", "message", f"n{i}", rng.choice(people), iso(T0 + timedelta(minutes=rng.randint(0, 60 * 24 * 90))),
                          rng.choice(chatter), channel=rng.choice(["engineering", "random", "product"])))
    return people, msgs, tickets, prs, expected


def timeit(fn, n=20):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    xs.sort()
    return {"p50_ms": round(statistics.median(xs), 2), "p95_ms": round(xs[int(len(xs) * 0.95) - 1], 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=int, default=200)
    ap.add_argument("--noise", type=int, default=20000)
    a = ap.parse_args()
    people, msgs, tickets, prs, expected = synth(a.features, a.noise)
    g = get_graph(GRAPH)
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass
    g = get_graph(GRAPH)
    out = {"features": a.features, "messages": len(msgs), "tickets": len(tickets), "prs": len(prs)}
    t = time.perf_counter()
    writer.apply_schema(g)
    writer.write_people(g, [{"id": p, "name": p, "role": "engineer"} for p in people])
    writer.write_tickets(g, tickets)
    writer.write_messages(g, msgs)
    writer.write_pull_requests(g, prs)
    out["ingest_s"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    resolve(g, "heuristic", log=lambda *_: None)
    out["resolve_s"] = round(time.perf_counter() - t, 2)
    out["nodes"] = g.query("MATCH (n) RETURN count(n)").result_set[0][0]
    out["relationships"] = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]

    found = {d["ticket"] for d in Q.drift(g)}
    tp = len(found & expected)
    out["drift_expected"], out["drift_found"] = len(expected), len(found)
    out["drift_precision"] = round(tp / len(found), 3) if found else 1.0
    out["drift_recall"] = round(tp / len(expected), 3) if expected else 1.0

    sample = sorted(expected)[: 20]
    out["query_drift_all"] = timeit(lambda: Q.drift(g), n=10)
    out["query_drift_one_ticket"] = timeit(lambda: Q.drift(g, ticket=random.choice(sample)))
    out["query_connection"] = timeit(lambda: Q.connection(g, "p0", "PR-1"))
    out["query_requirements_of_ticket"] = timeit(lambda: g.query("MATCH (q:Requirement {ticket: $t}) RETURN q.id", {"t": random.choice(sample)}))

    # live path: one incoming chat message -> write, resolve, classify, requirement chain, drift query
    from pipeline.extract import HeuristicExtractor
    from pipeline.live import process_message
    ex, n = HeuristicExtractor(), iter(range(10**6))
    out["live_message"] = timeit(lambda: process_message(Event(
        "slack", "message", f"live{next(n)}", "p1", "2026-06-01T10:00:00Z",
        f"Decision: the {WORDS[0]}0 report must include the last {random.randint(500, 900)} entries.", channel="product"), g=g, extractor=ex))
    g.delete()

    print(json.dumps(out, indent=1))
    res = Path(__file__).resolve().parent / "results"
    res.mkdir(exist_ok=True)
    (res / f"scale_{a.features}x{a.noise}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if out["drift_precision"] < 1 or out["drift_recall"] < 1:
        raise SystemExit("drift detection degraded at scale")


if __name__ == "__main__":
    main()
