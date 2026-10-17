"""Rules router on questions that are NOT in benchmark/questions.json: unknown ids, PR ids written loosely,
ticket-scoped questions, and a topic the graph doesn't know. Each case was a silent misroute before."""

import pytest

from agent.router import entities
from graph.db import get_db, get_graph


def _up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


def test_entities_parse_loose_pr_ids_and_tickets():
    assert entities("who wrote pr 6") == ["PR-6"]
    assert entities("who wrote PR6 and pull request 7?") == ["PR-6", "PR-7"]
    assert entities("is #5 linked to bd-103") == ["PR-5", "BD-103"]
    assert entities("how is liam connected to PR-6?") == ["PR-6"]


@pytest.fixture(scope="module")
def demo():
    if not _up():
        pytest.skip("FalkorDB not reachable")
    from graph.db import _org, org_graph_name, set_org
    from pipeline.build import build_graph

    name = org_graph_name("routertest")
    build_graph(name, "heuristic", log=lambda *_: None)
    token = set_org("routertest")
    yield
    _org.reset(token)
    get_graph(name).delete()


def ask(q):
    from agent.router import ask as _ask

    return _ask(q)["answer"].split("\n\nEvidence:")[0]


def test_unknown_ticket_says_so(demo):
    assert ask("is BD-999 stale") == "I couldn't find BD-999 in the graph."
    assert ask("how is maya connected to BD-999") == "I couldn't find BD-999 in the graph."


def test_non_ticket_ids_are_not_treated_as_missing_tickets(demo):
    assert "couldn't find" not in ask("does GPT-4 help with the csv export?")


def test_loose_pr_id(demo):
    assert "written by sofia" in ask("who wrote pr 6")


def test_ticket_scoped_answer_is_about_that_ticket(demo):
    a = ask("is BD-102 up to date")
    assert a.startswith("BD-102 (") and "No open drift on BD-102" in a
    assert "BD-101 still says" not in a


def test_named_pr_gets_its_own_status(demo):
    a = ask("did PR #6 ship the right thing?")
    assert a.startswith("PR #6 shipped the old version after the decision on BD-101")


def test_weak_feature_match_is_flagged(demo):
    a = ask("any drift on the mobile app push notifications?")
    assert a.startswith("(Low-confidence match: I read this as being about SLA breach notifications.)")
