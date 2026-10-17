"""The agent that gets work done (pipeline/work.py): plan a drift's fix from the graph, let only the ticket's owners
apply it, open follow-ups assigned to the people who own the stale work, keep them across rebuilds, and do all of it
from a chat thread. Plus the agent guardrails: read-only tools and the post-generation id check."""

import dataclasses

import pytest

from graph import db
from graph.queries import drift


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
GRAPH = "test_work"


@pytest.fixture()
def g(monkeypatch):
    from pipeline import llm
    from pipeline.build import build_graph

    # commands and tools call get_graph(): point it at the test graph
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, falkordb_graph=GRAPH))
    monkeypatch.setattr(llm, "available", lambda ttl=300.0: False)
    graph = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    yield graph
    db.get_graph(GRAPH).delete()


def _sla(g):
    return next(d["requirement"] for d in drift(g) if d["ticket"] == "BD-103")


def test_plan_assigns_each_part_to_its_owner(g):
    from pipeline.work import plan

    p = plan(g, _sla(g))
    assert [(i["kind"], i["target"]) for i in p["items"]] == [("ticket", "BD-103"), ("pr", "PR-5"), ("doc", "DOC-2")]
    by = {i["target"]: i["assignee"] for i in p["items"]}
    assert by["PR-5"] == "dev" and by["DOC-2"] == "dev"  # dev wrote PR #5 and DOC-2
    assert set(p["can_apply"]) == {"maya", "dev"}  # BD-103's creator and assignee
    assert "dev" not in p["tell"] and "maya" not in p["tell"] and p["tell"]


def test_only_owners_can_apply_and_apply_does_the_work(g):
    from pipeline.work import NotAllowed, apply, tasks

    req = _sla(g)
    with pytest.raises(NotAllowed, match="Maya Chen"):
        apply(g, req, "zara")
    assert req in {d["requirement"] for d in drift(g)}
    out = apply(g, req, "maya")
    assert out["ticket"] == "BD-103" and req not in {d["requirement"] for d in drift(g)}
    t = tasks(g)
    assert [(x["target"], x["assignee"], x["approved_by"]) for x in t] == [("PR-5", "dev", "maya"), ("DOC-2", "dev", "maya")]
    edges = g.query("MATCH (t:Task {target: 'PR-5'})-[r]-(x) RETURN type(r), x.id ORDER BY type(r)").result_set
    assert ["APPROVED", "maya"] in edges and ["ASSIGNED_TO", "dev"] in edges and ["FIXES", "PR-5"] in edges and ["FOR", req] in edges


def test_follow_ups_survive_a_full_rebuild_and_close_by_their_assignee(g):
    from pipeline.build import build_graph
    from pipeline.work import NotAllowed, apply, complete, tasks

    apply(g, _sla(g), "maya")
    g2 = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    t = tasks(g2)
    assert [x["target"] for x in t] == ["PR-5", "DOC-2"]
    assert g2.query("MATCH (t:Task)-[:FOR]->(:Requirement) RETURN count(t)").result_set[0][0] == 2
    with pytest.raises(NotAllowed):
        complete(g2, t[0]["num"], "zara")
    complete(g2, t[0]["num"], "dev")
    assert [x["target"] for x in tasks(g2)] == ["DOC-2"]


def test_chat_thread_commands(g):
    from bots.commands import handle

    req = _sla(g)
    plan = handle("plan", actor="zara", requirement=req)
    assert plan.startswith("*Plan for BD-103") and "→ *dev*" in plan and "Maya Chen (created it) or Dev Patel (assigned)" in plan
    assert handle("fix it", actor="zara", requirement=req).startswith("🔒 Only BD-103's owners")
    done = handle("fix it", actor="maya", requirement=req)
    assert done.startswith("✅ Done. BD-103 now carries the decision") and "T-1" in done and "T-2" in done
    assert "T-1" in handle("my tasks", actor="dev") and "No open follow-ups" in handle("my tasks", actor="zara")
    assert handle("done T-1", actor="dev").startswith("✅ T-1 closed by dev")
    # outside a thread the ticket is named instead
    assert handle("plan BD-101", actor="zara").startswith("*Plan for BD-101")
    assert handle("hello there") is None


def test_keep_old_scope_from_chat_needs_rights(g):
    from bots.commands import handle

    req = _sla(g)
    assert handle("keep the old scope", actor="liam", requirement=req).startswith("🔒")
    assert handle("keep the old scope", actor="dev", requirement=req).startswith("Recorded: dev keeps the old scope")
    assert req not in {d["requirement"] for d in drift(g)}


def test_router_answers_plan_and_tasks(g):
    from agent.router import ask

    a = ask("What needs to happen to fix BD-103?")
    assert a["intent"] == "plan" and "PR #5" in a["answer"] and "→ dev" in a["answer"]
    assert all("ms" in c for c in a["tool_calls"])  # the trace carries latency
    assert ask("What are the open follow-ups?")["answer"].startswith("No open follow-ups")


def test_agent_tools_cannot_write(g):
    from agent.tools import _g

    with pytest.raises(Exception, match="(?i)read-only"):
        _g().query("CREATE (:Sneaky {id: 'x'})")


def test_post_generation_check_flags_ids_no_tool_returned():
    from agent.agent import ungrounded

    seen = '{"rows": [{"ticket": "BD-103", "pr": 5}]}'
    assert ungrounded("BD-103 shipped in #5.", "q", seen) == []
    assert ungrounded("BD-123 shipped in #9.", "q", seen) == ["#9", "BD-123"]
    assert ungrounded("BD-101 is stale.", "Is BD-101 stale?", "") == []
