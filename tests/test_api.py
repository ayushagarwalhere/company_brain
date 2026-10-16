"""HTTP-level tests for the FastAPI app, on an isolated graph. Skipped if FalkorDB isn't reachable."""
import dataclasses
import hashlib
import hmac
import json

import pytest

from graph import db

GRAPH = "test_api_brain"


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
    # every get_graph() call goes through graph.db, so pointing its settings at a test graph isolates the app
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


def test_read_endpoints(client):
    assert client.get("/api/health").json()["ok"] is True
    stats = client.get("/api/stats").json()
    assert {n["label"] for n in stats["nodes"]} >= {"Message", "Ticket", "PullRequest", "Document", "Feature"}
    drift = client.get("/api/drift").json()
    assert {d["ticket"] for d in drift} == {"BD-101", "BD-103"}
    assert all(d["path"].startswith("(Person ") for d in drift)
    feats = client.get("/api/features").json()
    f = next(x for x in feats if "BD-101" in x["tickets"])
    assert f["drift"] is True
    assert client.get(f"/api/features/{f['id']}/graph").json()["nodes"]
    assert any(e["drift"] for e in client.get(f"/api/features/{f['id']}/timeline").json())
    retro = client.get("/api/retro/s1").json()
    assert len(retro["decided"]) == 3 and retro["diverged"]
    cov = client.get("/api/coverage").json()
    assert [p["pr"] for p in cov["orphan_prs"]] == [1]
    assert client.get("/api/search", params={"q": "breach email"}).json()
    assert client.get("/api/people/sofia").json()["name"] == "Sofia Alvarez"
    assert client.get("/api/connect", params={"a": "liam", "b": "PR-6"}).json()["paths"]
    assert client.get("/api/people/nobody").status_code == 404


def test_ask_uses_rules_agent_without_llm(client):
    r = client.post("/api/ask", json={"question": "Who owns BD-101?"}).json()
    assert r["engine"] == "rules" and "Sofia" in r["answer"]


def test_simulate_publishes_event(client):
    from api import bus
    r = client.post("/api/simulate", json={"text": "Decision: dark mode must also ship a high-contrast theme, BD-105.",
                                           "author": "zara"}).json()
    assert r["status"] == "drift" and r["ticket"] == "BD-105"
    assert bus.recent[-1]["type"] == "drift"


def test_ticket_webhook_unrelated_edit_keeps_drift_then_real_edit_resolves(client):
    before = {d["requirement"] for d in client.get("/api/drift").json() if d["ticket"] == "BD-101"}
    typo = client.post("/api/ingest/ticket", json={"ticket": "BD-101", "description":
        "Admins can export tickets created in the last 30 days as a CSV file. Columns: id, subject, status, created_at, assignee. (typo fixed)"}).json()
    assert typo["status"] == "updated" and set(typo["still_drifting"]) == before and not typo["resolved"]
    real = client.post("/api/ingest/ticket", json={"ticket": "BD-101", "description":
        "Admins can export tickets for any custom date range up to 12 months as CSV, including all custom fields as extra columns."}).json()
    assert set(real["resolved"]) == before and not real["still_drifting"]


def test_github_webhook_signature_and_implements(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    payload = {"action": "closed", "pull_request": {
        "number": 99, "title": "BD-103: warn 15 minutes before SLA breach in the team's Slack channel",
        "body": "Fixes BD-103. Sends the warning 15 minutes before the breach to the team's Slack channel; email notifications dropped.",
        "html_url": "https://github.com/example/brightdesk/pull/99", "state": "closed",
        "user": {"login": "dev"}, "created_at": "2026-10-10T08:00:00Z", "merged_at": "2026-10-10T09:00:00Z"}}
    raw = json.dumps(payload).encode()
    bad = client.post("/api/ingest/github", content=raw, headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    ok = client.post("/api/ingest/github", content=raw, headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig}).json()
    assert ok["tickets"] == ["BD-103"] and ok["implements"]
    assert "req:m_sla_05" in ok["resolved"]
    assert "BD-103" not in {d["ticket"] for d in client.get("/api/drift").json()}


def test_reset_rebuilds(client):
    assert client.post("/api/demo/reset").json()["rebuilt_with"] in {"heuristic", "deepseek", "oracle"}
    assert {d["ticket"] for d in client.get("/api/drift").json()} == {"BD-101", "BD-103"}


def test_ingest_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "t0ken")
    body = {"ticket": "BD-110", "description": "Onboarding step 2 says Receive. (copy check)"}
    assert client.post("/api/ingest/ticket", json=body).status_code == 401
    assert client.post("/api/ingest/ticket", json=body, headers={"X-Ingest-Token": "nope"}).status_code == 401
    assert client.post("/api/ingest/ticket", json=body, headers={"Authorization": "Bearer t0ken"}).status_code == 200
    assert client.post("/api/demo/reset").status_code == 401


def test_cached_reads_invalidate_on_write(client):
    first = client.get("/api/drift").json()
    hits_before = client.get("/api/cache").json()["hits"]
    assert client.get("/api/drift").json() == first                     # served from cache
    assert client.get("/api/cache").json()["hits"] == hits_before + 1
    target = next(d for d in first if d["ticket"] == "BD-103")
    client.post("/api/drift/dismiss", json={"requirement": target["requirement"], "actor": "arjun"})
    assert "BD-103" not in {d["ticket"] for d in client.get("/api/drift").json()}  # write bumped the version


def test_orgs_are_isolated_graphs(client):
    from api import bus
    from graph import db as gdb
    assert client.get("/api/drift", headers={"X-Org": "Bad Org!"}).status_code == 400
    out = client.post("/api/orgs/acme/bootstrap").json()
    try:
        assert out["graph"].endswith("__acme") and out["nodes"] > 300
        assert "acme" in client.get("/api/orgs").json()["orgs"]
        acme = client.get("/api/drift", headers={"X-Org": "acme"}).json()
        assert {d["ticket"] for d in acme} == {"BD-101", "BD-103"}
        req = next(d["requirement"] for d in acme if d["ticket"] == "BD-101")
        client.post("/api/drift/dismiss", json={"requirement": req, "actor": "maya"}, headers={"X-Org": "acme"})
        assert bus.recent[-1]["org"] == "acme"
        assert "BD-101" not in {d["ticket"] for d in client.get("/api/drift", headers={"X-Org": "acme"}).json()}
        # the default org's graph is untouched
        assert "BD-101" in {d["ticket"] for d in client.get("/api/drift").json()}
        assert client.get("/api/orgs?org=acme").json()["current"] == "acme"
    finally:
        gdb.get_graph(out["graph"]).delete()


def test_events_from_other_processes_reach_this_one(client):
    """A bot in another process publishes on the FalkorDB/Redis channel; the API forwards it to its SSE clients."""
    import time as _t
    from api import bus
    from graph import db as gdb
    evt = {"type": "drift", "at": _t.time(), "org": "default", "ticket": "BD-999", "author": "bot-test"}
    gdb.get_db().connection.publish(bus.CHANNEL, json.dumps({"origin": "another-process", "event": evt}))
    for _ in range(40):
        if any(e.get("ticket") == "BD-999" for e in bus.recent):
            break
        _t.sleep(0.05)
    assert any(e.get("ticket") == "BD-999" for e in bus.recent)
