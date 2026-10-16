"""Human actions (dismissals, write-to-ticket) must survive a re-resolve and a full rebuild."""

import pytest

from graph.db import get_db, get_graph
from graph.queries import drift


def _up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
GRAPH = "test_human_actions"


@pytest.fixture()
def g():
    from pipeline.build import build_graph

    graph = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    yield graph
    get_graph(GRAPH).delete()


def _req(g, ticket):
    return next(d["requirement"] for d in drift(g) if d["ticket"] == ticket)


def _state(g):
    open_drift = {d["requirement"] for d in drift(g)}
    dismissals = g.query("MATCH (p:Person)-[:MADE]->(d:Decision {kind: 'dismissal'})-[:DISMISSES]->(r:Requirement) " "RETURN d.id, p.id, r.id").result_set
    return open_drift, dismissals


def test_dismissal_and_write_back_survive_a_re_resolve(g):
    from pipeline.actions import dismiss, write_to_ticket
    from pipeline.resolve import resolve

    sla, export = _req(g, "BD-103"), _req(g, "BD-101")
    dismiss(g, sla, "maya")
    write_to_ticket(g, export, "maya")
    before = _state(g)
    assert sla not in before[0] and export not in before[0] and before[1]
    resolve(g, "heuristic", log=lambda *_: None)
    after = _state(g)
    assert after == before, after


def test_dismissal_and_write_back_survive_a_full_rebuild(g):
    from pipeline.actions import dismiss, write_to_ticket
    from pipeline.build import build_graph

    sla, export = _req(g, "BD-103"), _req(g, "BD-101")
    dismiss(g, sla, "maya")
    write_to_ticket(g, export, "maya")
    before = _state(g)
    g2 = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    after = _state(g2)
    assert after == before, after
    v = g2.query("MATCH (t:Ticket {id: 'BD-101'}) RETURN t.description").result_set[0][0]
    assert "12 months" in v  # the written-back requirement is still the ticket's text
