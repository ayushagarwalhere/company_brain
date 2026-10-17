"""The demo's cross-tool features, end to end over HTTP on an isolated graph (skipped if FalkorDB isn't reachable):
* one question answered across four systems: Slack -> Notion -> the tracker -> HR
* a live stream: a chat decision cancels a project, a new ticket lands in another, and the agent's next answer changes
* the company graph behind the interactive map
"""

import dataclasses

import pytest

from graph import db

GRAPH = "test_cross_tool"


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")

QUESTION = "Why is the database migration delayed and who can approve an override?"
ACTIVE = "What projects are currently active?"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "settings", dataclasses.replace(db.settings, falkordb_graph=GRAPH))
    from pipeline import llm

    mp.setattr(llm, "available", lambda ttl=300.0: False)  # deterministic: heuristic extractor + rules agent
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    ingest(reset=True)
    resolve(db.get_graph(), "heuristic", log=lambda *_: None)
    from api.main import app

    with TestClient(app) as c:
        yield c
    db.get_graph().delete()
    mp.undo()


def test_hr_records_reach_the_graph(client):
    g = db.get_graph()
    rows = g.query("MATCH (p:Person {id: 'dev'})-[:REPORTS_TO]->(m:Person) RETURN m.id, p.ooo_until").result_set
    assert rows == [["arjun", "2026-10-16"]]
    # access groups come from HR too, so leads see what's shared with leads whatever people.json says
    assert "leads" in client.get("/api/whoami", headers={"X-User": "maya"}).json()["grants"]


def test_one_question_hops_across_four_systems(client):
    r = client.post("/api/ask", json={"question": QUESTION}).json()
    assert r["intent"] == "blocked"
    a = r["answer"]
    assert "BD-116" in a and "out of office" in a and "Arjun Mehta" in a and "Dev's manager" in a
    # the evidence walks chat -> doc -> ticket -> assignee -> manager
    assert "-[:REFERS_TO]->(Document DOC-6)-[:MENTIONS]->(Ticket BD-116)-[:ASSIGNED_TO]->(Person dev)-[:REPORTS_TO]->(Person arjun)" in r["paths"][0]
    labels = {s["label"] for s in r["sources"]}
    assert {"Slack #engineering", "Notion (demo)", "Linear (demo)", "HR (demo)"} <= labels  # sample data, labelled as such


def test_nothing_blocked_means_no_made_up_reason(client):
    r = client.post("/api/ask", json={"question": "Why is the onboarding copy delayed?"}).json()
    assert "BD-116" not in r["answer"]


def test_live_stream_changes_the_next_answer(client):
    before = client.post("/api/ask", json={"question": ACTIVE}).json()
    assert before["intent"] == "projects" and "3 active projects" in before["answer"]

    # someone who may not decide it: kept as a message, the project stays active
    r = client.post("/api/simulate", json={"text": "We are cancelling Project Gamma effective immediately.", "author": "zara", "channel": "product"}).json()
    assert r["status"] == "project-status" and r["change"]["status"] == "no-rights"
    assert "3 active projects" in client.post("/api/ask", json={"question": ACTIVE}).json()["answer"]

    # a lead cancels it: the graph changes and so does the answer, with the message as evidence
    r = client.post(
        "/api/simulate",
        json={"text": "We are cancelling Project Gamma effective immediately. Theming moves to next year.", "author": "maya", "channel": "product"},
    ).json()
    assert r["change"] == {**r["change"], "status": "changed", "to": "cancelled", "project": "gamma"}
    after = client.post("/api/ask", json={"question": ACTIVE}).json()
    assert "2 active projects" in after["answer"] and "Not active: Project Gamma is cancelled (maya" in after["answer"]
    assert any("-[:CHANGES_STATUS]->(Project gamma)" in p for p in after["paths"])

    # a new ticket lands in Project Beta and shows up in the answer
    t = client.post(
        "/api/ingest/ticket/new", json={"title": "PDF version of the weekly SLA report", "creator": "maya", "assignee": "sofia", "project": "beta"}
    ).json()
    assert t["ticket"] == "BD-117" and t["project_name"] == "Project Beta"
    assert "BD-117" in client.post("/api/ask", json={"question": ACTIVE}).json()["answer"]

    # the stream shows both, newest first, with what they changed
    s = client.get("/api/stream?limit=5").json()
    new = next(x for x in s[:3] if x["kind"] == "ticket")  # all three arrived within the same second
    assert new["id"] == "BD-117" and new["project"] == "Project Beta" and new["assignee"] == "sofia"
    cancel = next(x for x in s if x["kind"] == "message" and x["project_to"] == "cancelled")
    assert cancel["who"] == "maya" and cancel["project"] == "Project Gamma"


def test_company_graph_for_the_map(client):
    cg = client.get("/api/company-graph").json()
    types = {n["type"] for n in cg["nodes"]}
    assert {"Person", "Team", "Project", "Client", "Deliverable", "Document", "Ticket"} <= types
    rels = {e["rel"] for e in cg["edges"]}
    assert {"REPORTS_TO", "MEMBER_OF", "OWNS", "INCLUDES", "NEEDS", "BLOCKS", "MENTIONS"} <= rels
    # the confidential doc is only on the map for those allowed to see it
    assert "DOC-5" not in {n["id"] for n in cg["nodes"]}
    assert "DOC-5" in {n["id"] for n in client.get("/api/company-graph", headers={"X-User": "maya"}).json()["nodes"]}
