"""Noise robustness: inject 500 messages that change no requirement and count false drift alerts.

    python -m benchmark.noise          # -> benchmark/results/noise.json

The noise set is fixed (seed 0) and was written before any mitigation existed:
  * 250 REAL comments sampled from the GitHub snapshots in data/real/ (bug reports, PR reviews,
    status, bots). Off-topic for the synthetic company, and not written by me.
  * 250 ON-TOPIC synthetic messages about the scenario's own tickets, 50 each of: status updates,
    code-review remarks, volunteer proposals, questions, customer requests. These categories are
    the failure patterns found on real data (benchmark/real_data.py), so this half is deliberately
    adversarial for the rules extractor. None of them is a requirement change.
Each noise message gets a random author, channel and time inside the scenario window, as a
top-level message. Graph: built in a separate graph, the demo graph is untouched.

Reported twice: without and with the one mitigation, decision rights (pipeline/resolve.py:
has_decision_rights), so the before/after comes from the same noise.
"""
import json
import random
from datetime import datetime, timedelta, timezone

from benchmark.real_data import load_snapshot
from pipeline.events import Event

SEED, N_REAL, N_SYNTH = 0, 250, 250
GRAPH = "bench_noise"
CHANNELS = [("discord", "design"), ("discord", "engineering"), ("discord", "random"),
            ("slack", "engineering"), ("slack", "product"), ("slack", "support-escalations")]
START, END = datetime(2026, 9, 14, 3, 36, tzinfo=timezone.utc), datetime(2026, 10, 9, 12, 27, tzinfo=timezone.utc)
GOLD_DRIFT_MESSAGES = {"m_exp_12", "m_sla_05"}

TOPICS = [  # ticket, what it is, alternatives that appear in its discussion
    ("BD-101", "the CSV export", ("CSV", "XLSX"), ("30 days", "12 months")),
    ("BD-102", "the export button", ("toolbar", "kebab menu"), ("one click", "two clicks")),
    ("BD-103", "SLA breach notifications", ("email", "Slack"), ("at breach", "15 minutes before")),
    ("BD-104", "the SLA settings page", ("a dropdown", "free text"), ("4 hours", "8 hours")),
    ("BD-105", "dark mode", ("the header", "settings"), ("system default", "light")),
    ("BD-106", "the theme tokens", ("CSS variables", "a JS theme object"), ("12 tokens", "20 tokens")),
]
TEMPLATES = {
    "status": [
        "PR for {t} is up: the code now reads the value from config instead of hardcoding it. Ready for review.",
        "Merged the fix for {t} this morning, deployed to staging.",
        "{t} update: tests are green, {what} works with {a} on staging.",
        "Rebased the {what} branch ({t}) on main, no functional change.",
        "Heads up: {t} is blocked on CI, will retry after lunch.",
    ],
    "code_review": [
        "Review on the {what} PR ({t}): let's use a constant instead of the magic number in the handler.",
        "Agreed with your comment on the {t} PR, I renamed the helper and added a test.",
        "Nit on {t}: we should use the shared date util instead of parsing by hand.",
        "LGTM on the {what} PR, one small suggestion about the error message.",
        "Let's move the {what} helper into utils, it is duplicated in two files ({t}).",
    ],
    "volunteer": [
        "I'd like to pick up {t}. I'll start with the {what} part and open a draft PR.",
        "Happy to take {t} if nobody has it, I'll look at the {what} code tomorrow.",
        "Proposal for {t}: what if {what} used {b} instead of {a}? Just an idea, not urgent.",
        "I can help with {what} ({t}) next sprint if Kenji is busy.",
        "Idea: we could do {c2} instead of {c1} for {what} someday. Parking it here.",
    ],
    "question": [
        "Does {t} still need {a}, or did we move on from that?",
        "Quick q on {what}: are we doing {b} instead of {a}?",
        "Who owns {t} these days?",
        "Is {what} ({t}) going out this sprint?",
        "Where is the spec for {what}? Want to check the {c1} part.",
    ],
    "customer": [
        "Customer asked whether {what} could support {b} instead of {a}. Logging it as a request.",
        "Acme wants {c2} for {what}. Not agreed, just passing it on ({t}).",
        "Two customers asked about {what} today, both happy with {a} as is.",
        "Support ticket: user confused by {what}, they expected {b}. FYI for {t}.",
        "Customer request: could {what} default to {c2}? Told them I'd check with product.",
    ],
}


def _when(rng) -> str:
    return (START + timedelta(seconds=rng.uniform(0, (END - START).total_seconds()))).strftime("%Y-%m-%dT%H:%M:%SZ")


def noise_messages(seed: int = SEED) -> list[Event]:
    from connectors import scenario
    rng = random.Random(seed)
    people = [p["id"] for p in scenario.people()]
    real = [c["body"] for repo in ("FalkorDB/FalkorDB", "excalidraw/excalidraw") for c in load_snapshot(repo)["comments"] if c["body"]]
    out = []
    for i, body in enumerate(rng.sample(sorted(real), N_REAL)):
        src, ch = rng.choice(CHANNELS)
        out.append(Event(source=src, kind="message", id=f"noise:real:{i}", author=rng.choice(people), ts=_when(rng),
                         text=body[:1500], url="", channel=ch, extra={"noise": "real"}))
    kinds = list(TEMPLATES)
    for i in range(N_SYNTH):
        kind = kinds[i % len(kinds)]
        t, what, (a, b), (c1, c2) = rng.choice(TOPICS)
        text = rng.choice(TEMPLATES[kind]).format(t=t, what=what, a=a, b=b, c1=c1, c2=c2)
        src, ch = rng.choice(CHANNELS)
        out.append(Event(source=src, kind="message", id=f"noise:{kind}:{i}", author=rng.choice(people), ts=_when(rng),
                         text=text, url="", channel=ch, extra={"noise": kind}))
    return out


def measure(g) -> dict:
    from graph.queries import drift, rows
    found = drift(g)
    flagged = [d["message"] for d in found]
    changes = [r["m"] for r in rows(g, "MATCH (m:Message)-[:CHANGES]->(:Requirement) RETURN m.id AS m")]
    by_kind: dict[str, int] = {}
    for m in flagged:
        if m.startswith("noise:"):
            k = m.split(":")[1]
            by_kind[k] = by_kind.get(k, 0) + 1
    return {"drift_alerts": len(found),
            "false_drift_alerts": sum(m.startswith("noise:") for m in flagged),
            "false_drift_alerts_by_noise_kind": dict(sorted(by_kind.items())),
            "true_drifts_found": len(GOLD_DRIFT_MESSAGES & set(flagged)), "true_drifts_total": len(GOLD_DRIFT_MESSAGES),
            "requirement_changes_from_noise": sum(m.startswith("noise:") for m in changes),
            "requirement_changes_from_scenario": sum(not m.startswith("noise:") for m in changes)}


def run(**resolve_kwargs) -> dict:
    from graph import writer
    from graph.db import get_graph
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    ingest(reset=True, graph_name=GRAPH)
    g = get_graph(GRAPH)
    writer.write_messages(g, noise_messages())
    resolve(g, "heuristic", log=lambda *_: None, **resolve_kwargs)
    return measure(g)


def main():
    from benchmark.run import HERE
    out = {"noise": {"real_github_comments": N_REAL, "synthetic_on_topic": N_SYNTH, "seed": SEED},
           "extractor": "heuristic (rules, no LLM)",
           "before (anyone can change a ticket from chat)": run(decision_rights=False),
           "after (decision rights: ticket creator or assignee only)": run(decision_rights=True)}
    print(json.dumps(out, indent=1))
    (HERE / "results" / "noise.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
