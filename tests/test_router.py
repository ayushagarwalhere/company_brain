"""The rules agent: scored intent routing, entity parsing, and loud failure (agent/router.py)."""
import pytest

from agent.router import entities, pick_intent


@pytest.mark.parametrize("q,intent", [
    ("How is liam connected to PR-6?", "connect"),
    ("Who knows the most about ticket export?", "who"),
    ("Which tickets and PRs are affected by the decision to send SLA warnings early?", "impact"),
    ("Is there any drift on the dark mode feature?", "drift"),
    ("What is the current requirement for the ticket CSV export?", "decided"),
    ("Show me the timeline of the export feature", "history"),
    ("Which PR added the export button?", "prs"),
    ("Give me an overview", "overview"),
])
def test_one_intent_each(q, intent):
    assert pick_intent(q) == intent


@pytest.mark.parametrize("q,intent", [
    # q03: used to be read as "list PRs" and never compared what shipped with the decision
    ("Does the export that shipped match what was decided? Which PR shipped it?", "decided"),
    ("Which pull request implemented the SLA notifications, and did it follow the latest decision?", "decided"),
    # the failing stress-test question: used to fall through to an overview
    ("Which pull requests shipped a requirement that was later changed in chat?", "drift"),
    ("Who owns BD-101 and which decision makes their shipped work stale?", "who"),
    ("Who decided that SLA warnings should go to Slack, and where?", "decided"),
])
def test_former_misroutes(q, intent):
    assert pick_intent(q) == intent


def test_unknown_question_has_no_intent():
    assert pick_intent("What is the weather in Pune?") is None


def test_entities_separate_tickets_from_prs():
    assert entities("Who owns BD-101?") == ["BD-101"]
    assert entities("Who wrote #6 and PR-7?") == ["PR-6", "PR-7"]


# ---------------------------------------------------------------- end to end on a throwaway org graph

def _up():
    try:
        from graph.db import get_db
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def org():
    if not _up():
        pytest.skip("FalkorDB not reachable")
    from graph.db import get_graph, org_graph_name, set_org
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    name = org_graph_name("routertest")
    ingest(reset=True, graph_name=name)
    resolve(get_graph(name), "heuristic", log=lambda *_: None)
    token = set_org("routertest")
    yield
    from graph.db import _org
    _org.reset(token)
    get_graph(name).delete()


def test_unknown_question_fails_loudly(org):
    from agent.router import ask
    out = ask("What is the weather in Pune?")
    assert out["intent"] == "unmatched" and "couldn't match" in out["answer"] and "connected" in out["answer"]


def test_prs_without_a_feature_fails_loudly(org):
    from agent.router import ask
    out = ask("Which PRs are the oldest?")
    assert "couldn't match" in out["answer"] and not out["answer"].startswith("Features:")


def test_who_with_a_pr_id_looks_up_the_pr_not_a_ticket(org):
    from agent.router import ask
    out = ask("Who wrote #6?")
    assert out["intent"] == "who" and "PR #6" in out["answer"] and "sofia" in out["answer"] and "BD-101" in out["answer"]


def test_q03_answers_with_the_shipping_pr_and_the_mismatch(org):
    from agent.router import ask
    out = ask("Does the export that shipped match what was decided? Which PR shipped it?")
    assert "#6" in out["answer"] and "30 days" in out["answer"] and "12 months" in out["answer"]
