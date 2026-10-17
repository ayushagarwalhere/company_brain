"""Docs kept in sync (chunks + embeddings in a FalkorDB vector index, MENTIONS edges, stale flags) and entity-level
access control (a regular employee can't get restricted content from the agent, the tools or any API endpoint)."""

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
GRAPH = "test_knowledge"


@pytest.fixture()
def g(monkeypatch):
    from pipeline import llm
    from pipeline.build import build_graph

    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, falkordb_graph=GRAPH))
    monkeypatch.setattr(llm, "available", lambda ttl=300.0: False)
    graph = build_graph(GRAPH, "heuristic", log=lambda *_: None)
    yield graph
    db.get_graph(GRAPH).delete()


def as_viewer(who, fn, *a):
    from pipeline.access import reset_viewer, set_viewer

    t = set_viewer(who)
    try:
        return fn(*a)
    finally:
        reset_viewer(t)


# ---------------------------------------------------------------- sync


def test_build_indexes_every_doc_into_chunks_with_vectors(g):
    docs = g.query("MATCH (d:Document) RETURN count(d)").result_set[0][0]
    rows = g.query("MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk) RETURN count(DISTINCT d), count(c), count(c.vec)").result_set[0]
    assert rows[0] == docs and rows[1] >= docs and rows[2] == rows[1]


def test_doc_edit_reembeds_only_changed_chunks_and_moves_its_edges(g):
    from pipeline.webhooks import doc_updated

    text = g.query("MATCH (d:Document {id: 'DOC-1'}) RETURN d.text").result_set[0][0]
    first = doc_updated(g, "DOC-1", text, "maya")["sync"]
    assert first["embedded"] == 0 and first["kept"] == first["chunks"]  # nothing changed, nothing re-embedded
    # append a paragraph that names BD-104: only the new/changed chunk is embedded, and a MENTIONS edge appears
    extra = "\n\nExports now also support JSON. See BD-104."
    s = doc_updated(g, "DOC-1", text + extra, "maya")["sync"]
    assert 1 <= s["embedded"] < s["chunks"] and "BD-104" in s["mentions"]
    # remove it again: the edge goes, while BD-101/BD-102 (declared in the doc's frontmatter) stay
    s = doc_updated(g, "DOC-1", text, "maya")["sync"]
    assert s["mentions_dropped"] == ["BD-104"]
    mentions = {r[0] for r in g.query("MATCH (:Document {id: 'DOC-1'})-[:MENTIONS]->(t:Ticket) RETURN t.id").result_set}
    assert mentions == {"BD-101", "BD-102"}


def test_vector_search_finds_the_right_document(g):
    from pipeline.knowledge import search

    assert search(g, "dark mode theming tokens", "maya")[0]["doc"] == "DOC-3"
    assert search(g, "onboarding copy guidelines", "maya")[0]["doc"] == "DOC-4"
    assert search(g, "tell me a joke", "maya") == []  # shares no word with any passage


# ---------------------------------------------------------------- access control


def test_restricted_doc_is_invisible_to_a_regular_employee(g):
    from pipeline.access import hidden
    from pipeline.knowledge import search

    assert hidden(g, "zara")["ids"] == ["DOC-5"] and hidden(g, None)["ids"] == ["DOC-5"]
    assert hidden(g, "maya")["ids"] == [] and hidden(g, "arjun")["ids"] == []  # leads; arjun is also its author
    assert all(h["doc"] != "DOC-5" for h in search(g, "salary bands", "zara"))
    assert search(g, "salary bands", "maya")[0]["doc"] == "DOC-5"


def test_salary_question_answered_only_for_people_allowed(g):
    from agent.router import ask

    zara = as_viewer("zara", ask, "What is everyone's salary?")
    assert zara["answer"] == "I don't have information on that you can access."
    assert "DOC-5" not in str(zara) and "Compensation" not in str(zara) and "120,000" not in str(zara)
    maya = as_viewer("maya", ask, "What is everyone's salary?")
    assert "Senior Engineer: 120,000 to 155,000" in maya["answer"] and "DOC-5" in maya["answer"]


def test_tools_never_hand_restricted_rows_to_the_model(g):
    from agent import tools

    out = as_viewer("zara", tools.call, "search_knowledge", {"query": "salary bands compensation"})
    assert "DOC-5" not in str(out)


def test_api_responses_are_redacted_per_viewer(g):
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        for path in ("/api/search?q=compensation", "/api/people/arjun"):
            assert "DOC-5" not in c.get(path, headers={"X-User": "zara"}).text, path
            assert "DOC-5" not in c.get(path).text, path  # anonymous
        assert "DOC-5" in c.get("/api/search?q=compensation", headers={"X-User": "maya"}).text


def test_sharing_change_takes_effect_at_once(g):
    from pipeline.access import hidden
    from pipeline.webhooks import doc_updated

    text = g.query("MATCH (d:Document {id: 'DOC-3'}) RETURN d.text").result_set[0][0]
    doc_updated(g, "DOC-3", text, "priya", acl=["leads"])
    assert "DOC-3" in hidden(g, "zara")["ids"] and "DOC-3" not in hidden(g, "priya")["ids"]  # the author keeps access
    assert g.query("MATCH (:Document {id: 'DOC-3'})-[:HAS_CHUNK]->(c:Chunk) RETURN c.acl").result_set[0][0] == ["leads", "person:priya"]
    doc_updated(g, "DOC-3", text, "priya", acl=[])
    assert "DOC-3" not in hidden(g, "zara")["ids"]


# ---------------------------------------------------------------- Google Drive connector (fake Drive API)


def test_gdrive_sync_creates_updates_restricts_and_removes(g, monkeypatch):
    from connectors import gdrive
    from pipeline.access import hidden

    drive = {
        "changes": [
            {
                "fileId": "F1",
                "file": {
                    "id": "F1",
                    "name": "Export spec",
                    "mimeType": gdrive.DOC_MIME,
                    "modifiedTime": "2026-10-17T10:00:00Z",
                    "owners": [{"emailAddress": "nobody@example.com"}],
                },
            }
        ],
        "text": "Exports support JSON too. Tracked in BD-102.",
        "perms": [{"type": "user", "emailAddress": "Maya@Brightdesk.io"}],
    }

    def fake_get(path, **params):
        if path == "/changes/startPageToken":
            return {"startPageToken": "1"}
        if path == "/changes":
            return {"changes": drive["changes"], "newStartPageToken": "2"}
        if path.endswith("/export"):
            return drive["text"]
        if path.endswith("/permissions"):
            return {"permissions": drive["perms"]}
        raise AssertionError(path)

    monkeypatch.setattr(gdrive, "_get", fake_get)
    out = gdrive.sync(g)
    assert out["created"] == ["gdoc:F1"] and out["page_token"] == "2"
    assert g.query("MATCH (:Document {id: 'gdoc:F1'})-[:MENTIONS]->(t:Ticket) RETURN t.id").result_set == [["BD-102"]]
    assert "gdoc:F1" in hidden(g, "zara")["ids"]  # shared with one user only
    drive["perms"], drive["text"] = [{"type": "domain", "domain": "brightdesk.io"}], "Exports support JSON and XML."
    out = gdrive.sync(g)
    assert out["updated"] == ["gdoc:F1"] and "gdoc:F1" not in hidden(g, "zara")["ids"]
    assert g.query("MATCH (:Document {id: 'gdoc:F1'})-[:MENTIONS]->() RETURN count(*)").result_set[0][0] == 0
    drive["changes"] = [{"fileId": "F1", "removed": True}]
    assert gdrive.sync(g)["removed"] == ["gdoc:F1"]
    assert g.query("MATCH (c:Chunk) WHERE c.id STARTS WITH 'gdoc:F1' RETURN count(c)").result_set[0][0] == 0


def test_gdrive_acl_from_sharing():
    from connectors.gdrive import acl_from_permissions

    assert acl_from_permissions([{"type": "anyone"}]) == []
    assert acl_from_permissions([{"type": "user", "emailAddress": "A@x.io"}, {"type": "group", "emailAddress": "hr@x.io"}]) == ["email:a@x.io", "email:hr@x.io"]
