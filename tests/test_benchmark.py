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
