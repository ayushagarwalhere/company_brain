"""One stale-PR rule everywhere (graph/queries.py PR_STATUS_LABEL): the drift card's tile count and edge label, the
evidence path and the Ask answer must agree for the demo's two drifts, BD-103 (PR #5) and BD-101 (PR #6). Both PRs
were merged AFTER the decision and implement the older requirement, so both are stale: "shipped the old version
after the decision". Before the fix the Ask answer said "PRs that shipped the old version: none".
"""

import pytest

from graph.db import get_db, get_graph


def _up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def demo():
    if not _up():
        pytest.skip("FalkorDB not reachable")
    from graph.db import _org, org_graph_name, set_org
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    name = org_graph_name("staletest")
    ingest(reset=True, graph_name=name)
    resolve(get_graph(name), "heuristic", log=lambda *_: None)
    token = set_org("staletest")
    yield get_graph(name)
    _org.reset(token)
    get_graph(name).delete()


CASES = [("BD-103", 5, "What does BD-103 say and is it still accurate?"), ("BD-101", 6, "Is there any drift on the ticket CSV export?")]


@pytest.mark.parametrize("ticket,pr,question", CASES)
def test_tile_count_edge_label_path_and_answer_agree(demo, ticket, pr, question):
    from agent.router import ask
    from agent.tools import drift_path
    from graph.queries import PR_STATUS_LABEL, drift

    d = next(x for x in drift(demo) if x["ticket"] == ticket)
    # tile count: the dashboard shows len(stale_prs)
    assert [p["pr"] for p in d["stale_prs"]] == [pr] and d["unmatched_prs"] == []
    # edge label: the dashboard labels the chip from status ("old_after" -> "after decision")
    p = d["stale_prs"][0]
    assert p["status"] == "old_after" and p["label"] == PR_STATUS_LABEL["old_after"] and p["implements"]
    # evidence path: same wording, and the IMPLEMENTS-older fact the answer must agree with
    path = drift_path(d)
    assert f"PullRequest #{pr}" in path and PR_STATUS_LABEL["old_after"] in path and "IMPLEMENTS older" in path
    assert "(check)" not in path
    # Ask answer: lists the PR as stale, never "none" when the path shows it implementing the older requirement
    answer = ask(question)["answer"]
    assert f"PRs that shipped the old version: #{pr} (after the decision)" in answer
    assert "PRs that shipped the old version: none" not in answer


def test_classification_rule_covers_all_three_cases():
    from graph.queries import classify_prs

    rows = [
        {"pr": 1, "merged_after": False, "implements": None},  # before the decision
        {"pr": 2, "merged_after": True, "implements": "older text"},  # after, implements the old version
        {"pr": 3, "merged_after": True, "implements": None},  # after, no link either way
        {"pr": None, "merged_after": None, "implements": None},  # OPTIONAL MATCH with no PR
    ]
    stale, unmatched = classify_prs(rows)
    assert [(p["pr"], p["status"]) for p in stale] == [(1, "old"), (2, "old_after")]
    assert [(p["pr"], p["status"]) for p in unmatched] == [(3, "unmatched")]
