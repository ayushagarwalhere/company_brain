"""The no-LLM benchmark baseline and the grader (no FalkorDB, no LLM)."""
from benchmark.run import QUESTIONS, baseline_extractive, corpus, grade
from pipeline.textsim import TfIdf


def test_extractive_baseline_returns_top_k_passages_verbatim():
    docs = corpus()
    index = TfIdf(docs)
    out = baseline_extractive("SLA breach email notification", index, docs, 3)
    assert len(out["retrieved"]) == 3
    assert out["answer"] == "\n".join(docs[d] for d in out["retrieved"])
    wider = baseline_extractive("SLA breach email notification", index, docs, 25)
    assert wider["retrieved"][:3] == out["retrieved"]


def test_grader_needs_every_group_and_zeroes_forbidden_claims():
    item = {"must": [["#6", "PR 6"], ["30 days"]], "must_not": [["90 days"]]}
    assert grade("PR 6 exports 30 days", item)["score"] == 1.0
    assert grade("PR 6 exports everything", item)["score"] == 0.5
    assert grade("PR 6, 30 days, later 90 days", item)["score"] == 0.0


def test_questions_are_well_formed():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids)) == 15
    assert all(q["must"] and all(g for g in q["must"]) for q in QUESTIONS)


def test_noise_set_is_fixed_and_never_a_scenario_message():
    from benchmark.noise import N_REAL, N_SYNTH, noise_messages
    a, b = noise_messages(), noise_messages()
    assert [m.text for m in a] == [m.text for m in b] and len(a) == N_REAL + N_SYNTH == 500
    assert all(m.id.startswith("noise:") for m in a)


def test_scale_qa_cross_feature_grading_is_f1_over_named_ids():
    from benchmark.qa_scale import grade_q
    q = {"ids": ["SC-0", "SC-6"], "pattern": r"SC-\d+"}
    assert grade_q("SC-0 and SC-6", q) == 1.0
    assert grade_q("SC-0 and SC-3", q) == 0.5            # one right, one wrong main ticket
    assert grade_q("SC-1 SC-2 (siblings never drift)", q) == 0.0
    assert grade_q("SC-0, SC-6, SC-1", q) == 1.0          # sibling tickets are ignored, not penalised


def test_scale_qa_questions_are_fixed():
    from benchmark.qa_scale import questions
    expected = {f"SC-{f * 3}" for f in range(0, 200, 2)}
    a, b = questions([], expected), questions([], expected)
    assert [q["q"] for q in a] == [q["q"] for q in b]
    assert sum(q["kind"] == "per-feature" for q in a) == 18 and sum(q["kind"] == "cross-feature" for q in a) == 3


def test_recall_samples_are_fixed_and_labelled():
    import json
    from pathlib import Path
    from benchmark.real_data import proposal_sample, recall_sample
    labels = json.loads((Path(__file__).resolve().parent.parent / "benchmark" / "real_data_recall_labels.json").read_text(encoding="utf-8"))
    urls = [c["url"] for c in recall_sample() + proposal_sample()]
    assert urls == [l["url"] for l in labels["labels"]] and len(urls) == 60


def test_sql_baseline_chain_vs_latest_on_a_buried_decision():
    """The relational baseline: with the version chain, drift is an anti-join; without it ("newest wins"),
    a later misread message on the same ticket buries the real decision (benchmark/sql_baseline.py)."""
    from benchmark.sql_baseline import SQL_CHAIN, SQL_LATEST, load
    out = {"requirements": [{"id": "req:T-1:v1", "ticket": "T-1", "origin": "ticket", "at_ms": 1, "text": "old"},
                            {"id": "req:m1", "ticket": "T-1", "origin": "chat", "at_ms": 2, "text": "the decision"},
                            {"id": "req:m2", "ticket": "T-1", "origin": "chat", "at_ms": 3, "text": "misread status update"}],
           "changes": [{"id": "req:m1", "msg": "m1", "author": "a"}, {"id": "req:m2", "msg": "m2", "author": "a"}],
           "ticket_feature": {"T-1": "f"}, "prs": [{"id": "PR-1", "number": 1, "merged_ms": 5}],
           "pr_links": {"PR-1": [("T-1", "hard", 1.0)]}, "implements": [{"pr": "PR-1", "r": "req:m2"}],
           "supersedes": [{"new": "req:m1", "old": "req:T-1:v1"}]}  # no chat->chat edge: m2 doesn't replace m1
    db = load(out)
    assert {r for r, _ in db.execute(SQL_CHAIN).fetchall()} == {"req:m1"}
    assert db.execute(SQL_LATEST).fetchall() == []  # newest is m2, and a PR "implements" it: the decision is buried
