"""End-to-end graph tests on a throwaway graph. Skipped if FalkorDB isn't reachable.

Uses the oracle extractor so they run without API keys: this checks ingestion,
resolution, the drift query and the live monitor, not the LLM.
"""
import pytest

from graph.db import get_db, get_graph

GRAPH = "test_company_brain"


def _falkordb_up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB not reachable")


@pytest.fixture(scope="module")
def g():
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    ingest(reset=True, graph_name=GRAPH)
    graph = get_graph(GRAPH)
    resolve(graph, "oracle", log=lambda *_: None)
    yield graph
    graph.delete()


def test_ingest_is_idempotent(g):
    from pipeline.ingest import counts, ingest
    before = counts(g)["nodes"]["Message"]
    ingest(graph_name=GRAPH)
    assert counts(g)["nodes"]["Message"] == before == 300


def test_drift_finds_exactly_the_planted_cases(g):
    from graph.queries import drift
    found = {(d["feature"], d["ticket"]): d for d in drift(g)}
    assert set(found) == {("feat_export", "BD-101"), ("feat_sla", "BD-103")}
    assert [p["pr"] for p in found[("feat_export", "BD-101")]["stale_prs"]] == [6]
    assert [p["pr"] for p in found[("feat_sla", "BD-103")]["stale_prs"]] == [5]
    assert found[("feat_sla", "BD-103")]["source"] == "discord"


def test_pr_without_ticket_id_is_resolved_by_proximity(g):
    from graph.queries import rows
    r = rows(g, "MATCH (:PullRequest {id: 'PR-7'})-[x:REFERENCES]->(t:Ticket) RETURN t.id AS t, x.how AS how")
    assert r == [{"t": "BD-102", "how": "proximity+semantic"}]


def test_resolution_scores(g):
    from benchmark.score_resolution import score
    s = score(g)
    for k in ("ticket_to_feature", "pr_to_ticket", "requirement_changes", "drift", "drift_stale_prs"):
        assert s[k]["f1"] == 1.0, (k, s[k])
    assert s["message_to_feature"]["precision"] == 1.0


def test_live_monitor_alerts_once(g):
    from pipeline.events import Event
    from pipeline.live import HeuristicExtractor, process_message, _last_alert
    _last_alert.clear()
    ev = Event("discord", "message", "test:live1", "zara", "2026-10-12T06:00:00Z",
               "Decision: dark mode must also ship a high-contrast theme, BD-105.", channel="design")
    r = process_message(ev, g=g, extractor=HeuristicExtractor())
    assert r["status"] == "drift" and r["ticket"] == "BD-105" and "Graph path" in r["alert"]
    _last_alert.clear()
    again = process_message(ev, g=g, extractor=HeuristicExtractor())
    assert again["status"] == "already-alerted"


def test_small_talk_is_ignored(g):
    from pipeline.events import Event
    from pipeline.live import HeuristicExtractor, process_message
    r = process_message(Event("slack", "message", "test:live2", "arjun", "2026-10-12T06:05:00Z", "lol nice weekend",
                              channel="engineering"), g=g, extractor=HeuristicExtractor())
    assert r["status"] == "ok" and r["feature"] is None


def test_heuristic_extractor_finds_planted_drift_without_llm():
    """The rule-based extractor (no LLM, no answer key) must reproduce the planted outcome."""
    from benchmark.score_resolution import score
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve
    name = GRAPH + "_heuristic"
    ingest(reset=True, graph_name=name)
    g2 = get_graph(name)
    try:
        resolve(g2, "heuristic", log=lambda *_: None)
        s = score(g2)
        assert s["drift"]["f1"] == 1.0 and s["drift_stale_prs"]["f1"] == 1.0, s["drift"]
        assert s["requirement_changes"]["precision"] == 1.0
    finally:
        g2.delete()


def test_write_to_ticket_and_dismiss_close_the_loop(g):
    """Runs last on the shared graph: both actions remove drift and leave an auditable trail."""
    from graph.queries import drift, rows
    from pipeline.actions import dismiss, write_to_ticket
    open_ = {d["requirement"]: d for d in drift(g)}
    sla = next(r for r, d in open_.items() if d["ticket"] == "BD-103")
    exp = next(r for r, d in open_.items() if d["ticket"] == "BD-101")
    out = write_to_ticket(g, sla, actor="maya")
    assert out["ticket"] == "BD-103"
    assert rows(g, "MATCH (:Ticket {id:'BD-103'})-[:STATES]->(v:Requirement)-[:SUPERSEDES]->(:Requirement {id:$r}) "
                   "RETURN v.id AS v", r=sla)[0]["v"] == out["version"]
    dismiss(g, exp, actor="arjun")
    assert rows(g, "MATCH (:Person {id:'arjun'})-[:MADE]->(:Decision {kind:'dismissal'})-[:DISMISSES]->(r:Requirement) "
                   "RETURN r.id AS r") == [{"r": exp}]
    remaining = {d["ticket"] for d in drift(g)}
    assert "BD-103" not in remaining and "BD-101" not in remaining


def test_rules_agent_answers_from_graph(g, monkeypatch):
    """Without an LLM key, ask() routes to graph tools and still answers with paths."""
    from agent import router
    monkeypatch.setattr(router, "get_graph", lambda: g)
    import agent.tools as tools
    monkeypatch.setattr(tools, "_g", lambda: g)
    r = router.ask("Which PR added the export button, and which ticket does it belong to?")
    assert "#7" in r["answer"] and "BD-102" in r["answer"] and "proximity" in r["answer"]
    r = router.ask("Who owns BD-103?")
    assert "Dev Patel" in r["answer"]
    r = router.ask("How is liam connected to PR-6?")
    assert r["paths"] and r["paths"][0].startswith("(Person liam)")
