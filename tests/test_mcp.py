"""The MCP server (agent/mcp_server.py) over its real HTTP transport at /mcp, on the demo company in an isolated graph:
a coding agent asking for BD-101 gets the requirement decided in Slack, not the ticket's stale text."""

import dataclasses

import pytest

from graph import db

GRAPH = "test_mcp_brain"
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "mcp-protocol-version": "2025-06-18"}


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "settings", dataclasses.replace(db.settings, falkordb_graph=GRAPH))
    from pipeline import llm

    mp.setattr(llm, "available", lambda ttl=300.0: False)
    from pipeline.ingest import ingest
    from pipeline.resolve import resolve

    ingest(reset=True)
    resolve(db.get_graph(), "heuristic", log=lambda *_: None)
    from api.main import app

    with TestClient(app) as c:
        yield c
    db.get_graph().delete()
    mp.undo()


def rpc(c, method, params=None, path="/mcp", headers=None):
    r = c.post(path, headers={**H, **(headers or {})}, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def call(c, tool, path="/mcp", headers=None, **args):
    import json

    res = rpc(c, "tools/call", {"name": tool, "arguments": args}, path, headers)
    assert not res.get("isError"), res
    return json.loads(res["content"][0]["text"])


def test_handshake_lists_the_tools_and_tells_the_agent_to_check_first(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert "current_spec" in init["instructions"] and "not the ticket's text" in init["instructions"]
    names = {t["name"] for t in rpc(client, "tools/list")["tools"]}
    assert names == {"current_spec", "drift", "who_knows", "decision_history", "impact", "find"}


def test_current_spec_gives_the_decision_made_in_slack_not_the_stale_ticket(client):
    s = call(client, "current_spec", ticket="bd-101")
    assert s["status"] == "TICKET_OUT_OF_DATE"
    assert "12 months" in s["current_requirement"] and "custom fields" in s["current_requirement"]
    assert "30 days" in s["ticket_still_says"]
    assert s["decided"]["by"] == "maya" and s["decided"]["where"].startswith("Slack #")
    assert [p["pr"] for p in s["shipped_old_version"]] == [6]  # PR #6 shipped the 30-day version
    assert s["evidence"] and "(Ticket BD-101)" in s["evidence"][0]
    assert "maya" in s["owners"] and s["people_to_ask"]


def test_a_ticket_nobody_changed_is_current_and_an_unknown_one_is_said_so(client):
    drifted = {d["ticket"] for d in call(client, "drift")["drift"]}
    assert drifted == {"BD-101", "BD-103"}  # the scenario's two planted drifts
    s = call(client, "current_spec", ticket="BD-102")
    assert s["status"] == "CURRENT" and s["current_requirement"]
    missing = call(client, "current_spec", ticket="ZZ-999")
    assert missing["found"] is False


def test_topics_resolve_from_ticket_ids_or_words(client):
    by_ticket = call(client, "who_knows", topic="BD-101")
    by_words = call(client, "who_knows", topic="csv export")
    assert by_ticket["feature"] == by_words["feature"] and by_ticket["people"][0]["person"] == "maya"
    hist = call(client, "decision_history", topic="BD-101")
    assert any("12 months" in (r["text"] or "") for r in hist["history"])
    assert call(client, "find", query="csv export")["tickets"][0]["ticket"] == "BD-101"
    assert call(client, "impact", target="Project Alpha", days=14)["impact"]


def test_the_org_header_selects_another_graph(client):
    s = call(client, "current_spec", headers={"X-Org": "mcp-empty-org"}, ticket="BD-101")
    assert s["found"] is False  # a team's graph never answers with the demo company's tickets


def test_stdio_tools_read_the_org_from_the_environment(client, monkeypatch):
    from agent import mcp_server

    monkeypatch.setenv("BRAIN_ORG", "mcp-empty-org")
    assert mcp_server.current_spec("BD-101", None)["found"] is False
    monkeypatch.delenv("BRAIN_ORG")
    assert mcp_server.current_spec("BD-101", None)["status"] == "TICKET_OUT_OF_DATE"
