"""Impact analysis ("if we delay Project Alpha by two weeks, which teams and client deliverables are hit?"), feature
maps, and the docs/access endpoints the dashboard uses."""

import dataclasses

import pytest

from graph import db


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
GRAPH = "test_impact"
PROMPT = "If we delay the launch of Project Alpha by two weeks, which other teams and downstream client deliverables will be impacted?"


@pytest.fixture(scope="module")
def g():
    from pipeline import llm
    from pipeline.build import build_graph

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "settings", dataclasses.replace(db.settings, falkordb_graph=GRAPH))
    mp.setattr(llm, "available", lambda ttl=300.0: False)
    graph = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    yield graph
    db.get_graph(GRAPH).delete()
    mp.undo()


def test_delay_ripples_through_blocks_to_projects_clients_and_teams(g):
    from pipeline.impact import impact_of_delay

    out = impact_of_delay(g, "Project Alpha", 14)
    alpha, beta = out["projects"]
    assert (alpha["id"], alpha["launch"], alpha["new_launch"]) == ("alpha", "2026-10-23", "2026-11-06")
    # beta waits on alpha through BD-108 -BLOCKS-> BD-109 and can't launch before it
    assert (beta["id"], beta["slip_days"], beta["via"]["from"], beta["via"]["to"]) == ("beta", 3, "BD-108", "BD-109")
    status = {d["client"]: (d["status"], d["slack_days"]) for d in out["deliverables"]}
    assert status == {"acme": ("misses", -7), "globex": ("tight", 4), "umbrella": ("on track", 7)}
    assert {t["id"] for t in out["teams"]} == {"backend", "web", "product", "cs"}
    assert "(Client acme)<-[:FOR]-(Deliverable acme-audit)-[:NEEDS]->(Project alpha)" in out["paths"]
    assert any("[:BLOCKS]->(Ticket BD-109)<-[:INCLUDES]-(Project beta)" in p for p in out["paths"])


def test_no_delay_moves_nothing_and_unknown_target_says_so(g):
    from pipeline.impact import impact_of_delay

    out = impact_of_delay(g, "alpha", 0)
    assert all(d["status"] != "misses" and not d["moved"] for d in out["deliverables"])
    assert impact_of_delay(g, "Project Zeta", 14)["target"] is None


def test_agent_answers_the_delay_question_from_the_graph(g):
    from agent.router import ask, delay_days

    assert (delay_days("two weeks"), delay_days("3 days"), delay_days("a month"), delay_days("soon")) == (14, 3, 30, 14)
    r = ask(PROMPT)
    assert r["intent"] == "delay" and [t["tool"] for t in r["tool_calls"]] == ["impact_of_delay"]
    assert "2026-11-06" in r["answer"] and "Project Beta slips 3 days" in r["answer"]
    assert "Acme Corp" in r["answer"] and "misses its due date by 7 days" in r["answer"]
    assert "Backend" in r["answer"] and "Customer Success" in r["answer"]


def test_feature_map_shows_who_introduced_each_spec_and_the_work(g):
    from pipeline.impact import feature_map

    m = feature_map(g, "feat_ticket_export_to_csv")
    reqs = {n["id"]: n for n in m["nodes"] if n["type"] == "Requirement"}
    introduced = {e["to"] for e in m["edges"] if e["rel"] == "INTRODUCED"}
    assert reqs and set(reqs) == introduced  # every spec version has the person who introduced it
    assert any(n.get("status") == "drift" for n in reqs.values())
    rels = {e["rel"] for e in m["edges"]}
    assert {"MEMBER_OF", "ASSIGNED_TO", "AUTHORED", "REFERENCES", "INCLUDES", "NEEDS", "FOR", "BLOCKS"} <= rels
    types = {n["type"] for n in m["nodes"]}
    assert {"Team", "Person", "Ticket", "PullRequest", "Project", "Deliverable", "Client"} <= types


def test_api_impact_projects_and_map(g):
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        assert [p["id"] for p in c.get("/api/projects").json()] == ["gamma", "alpha", "beta"]
        out = c.get("/api/impact?target=alpha&days=14").json()
        assert out["graph"]["nodes"] and {"Team", "Deliverable", "Client"} <= {n["type"] for n in out["graph"]["nodes"]}
        assert c.get("/api/impact?target=zeta").status_code == 404
        assert c.get("/api/features/feat_dark_mode/map").json()["nodes"]


def test_docs_list_stats_and_edits_follow_the_viewer(g):
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        ids = lambda who: [d["id"] for d in c.get("/api/docs", headers={"X-User": who} if who else {}).json()]  # noqa: E731
        assert "DOC-5" in ids("maya") and "DOC-5" not in ids("zara") and "DOC-5" not in ids(None)
        docs = lambda who: next(n["n"] for n in c.get("/api/stats", headers={"X-User": who}).json()["nodes"] if n["label"] == "Document")  # noqa: E731
        assert docs("maya") == docs("zara") + 1  # a hidden doc isn't counted either
        # editing a doc you can't see answers exactly like a doc that doesn't exist
        r = c.post("/api/ingest/doc", json={"doc": "DOC-5", "text": "x", "actor": "zara"}, headers={"X-User": "zara"})
        assert r.status_code == 404
        assert "leads" in c.get("/api/whoami", headers={"X-User": "maya"}).json()["grants"]
        assert c.get("/api/whoami").json() == {"viewer": None, "grants": ["everyone"]}
