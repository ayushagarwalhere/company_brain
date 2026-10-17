"""Jira and Linear for a connected team: tickets with their description history, comments as discussion, people merged
with their Slack accounts, and the owner's Slack decision raising drift on a Jira or Linear ticket, as on the demo.
Jira, Linear and Slack are faked; FalkorDB is real."""

import tempfile
from pathlib import Path

import pytest

from graph import db


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")

MEMBERS = [
    {"id": "U1", "name": "maya.rao", "profile": {"real_name": "Maya Rao", "email": "maya@acme.io", "title": "Product Manager"}},
    {"id": "U2", "name": "sam", "profile": {"real_name": "Sam Kim", "email": "sam@acme.io", "title": "Backend Engineer"}},
    {"id": "U3", "name": "lee", "profile": {"real_name": "Lee Park", "email": "lee@acme.io", "title": "Support"}},
]
MAYA = {"accountId": "a1", "displayName": "Maya Rao"}  # Jira hides emails by default: matched by full name
SAM = {"accountId": "a2", "displayName": "Sam Kim"}
LEE = {"accountId": "a3", "displayName": "Lee Park"}
V1 = "Admins can export tickets created in the last 30 days as a CSV file."
V2 = "Admins can export tickets created in the last 30 days as a CSV file, with an assignee column."


class FakeSlack:
    def users_list(self, **kw):
        return {"members": MEMBERS}

    def users_info(self, user):
        return {"user": next(m for m in MEMBERS if m["id"] == user)}

    def usergroups_list(self, **kw):
        return {"usergroups": []}


def adf(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


@pytest.fixture()
def org(monkeypatch):
    from connectors import installs
    from pipeline import llm, teamsync

    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setenv("INSTALLS_PATH", str(Path(tmp.name) / "installs.json"))
    monkeypatch.setattr(llm, "available", lambda ttl=300.0: False)
    monkeypatch.setattr(teamsync, "_slack_client", lambda token: FakeSlack())
    org = installs.save_slack("T1", "Acme", "xoxb-test", "UBOT")["org"]
    yield org
    if db.org_graph_name(org) in db.get_db().list_graphs():
        db.get_graph(db.org_graph_name(org)).delete()
    tmp.cleanup()


def _in(org, fn):
    from graph.db import _org, set_org

    t = set_org(org)
    try:
        return fn()
    finally:
        _org.reset(t)


def _decide(org, slack_user, text, mid):
    from connectors.slack import TeamPeople
    from pipeline.events import Event
    from pipeline.live import process_message

    author = _in(org, lambda: TeamPeople(FakeSlack())(slack_user))
    ev = Event(source="slack", kind="message", id=mid, author=author, ts="2026-10-08T10:00:00Z", channel="product", text=text)
    return _in(org, lambda: process_message(ev))


def test_jira_issues_bring_their_whole_description_history_and_raise_drift(org, monkeypatch):
    from connectors import installs, jira
    from graph import queries as Q
    from graph.db import get_graph
    from pipeline import identity, teamsync

    issue = {
        "key": "ACME-1",
        "fields": {
            "summary": "Ticket export to CSV", "description": adf(V2), "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            "labels": ["export"], "reporter": MAYA, "assignee": SAM, "created": "2026-10-01T09:00:00.000+0000", "updated": "2026-10-02T09:00:00.000+0000",
            "resolutiondate": None,
            "comment": {"comments": [{"id": "10", "author": LEE, "created": "2026-10-03T09:00:00.000+0000", "body": adf("Acme asked about this.")}]},
        },
    }  # fmt: skip

    def fake_get(site, email, token, path, **params):
        assert path == "/rest/api/3/search/jql" and 'project = "ACME"' in params["jql"]
        return {"issues": [issue], "isLast": True}

    def history(site, email, token, key):  # one edit: Maya added the assignee column on Oct 2
        return [{"created": "2026-10-02T09:00:00.000+0000", "author": MAYA, "items": [{"field": "description", "fromString": V1, "toString": V2}]}]

    monkeypatch.setattr(jira, "_get", fake_get)
    installs.set_team(org, jira={"site": "https://acme.atlassian.net", "email": "x@acme.io", "token": "t", "project": "ACME"})
    out = teamsync.sync_team(org, full=True, jira_history=history)
    assert not out["errors"], out["errors"]
    assert out["jira"]["tickets"] == 1 and out["jira"]["comments"] == 1 and out["jira"]["new_versions"] == 2
    versions, actors = _in(org, lambda: get_graph().query("MATCH (t:Ticket {id: 'ACME-1'}) RETURN t.versions, t.version_actors").result_set[0])
    assert versions == [V1, V2] and actors == ["maya-rao", "maya-rao"]  # the full history, each version by its author
    who = {p["id"]: {a["platform"] for a in p["accounts"]} for p in _in(org, lambda: identity.directory(get_graph()))}
    assert who["maya-rao"] == {"slack", "jira"} and who["lee-park"] == {"slack", "jira"}
    assert _in(org, lambda: get_graph().query("MATCH (:Message {id: 'jirac:10'})-[:MENTIONS]->(t:Ticket) RETURN t.id").result_set) == [["ACME-1"]]

    r = _decide(org, "U1", "Decision: the export must support any date range up to 12 months, not only 30 days. ACME-1", "slack:C1:1.1")
    assert r["status"] == "drift" and r["ticket"] == "ACME-1", r
    assert [d["ticket"] for d in _in(org, lambda: Q.drift(get_graph()))] == ["ACME-1"]


def test_linear_issues_date_the_current_text_and_catch_later_edits(org):
    from connectors import installs
    from graph import queries as Q
    from graph.db import get_graph
    from pipeline import identity, teamsync

    state = {"description": V1, "updated": "2026-10-03T09:00:00.000Z"}

    def query(token, text, variables):
        assert variables["team"] == "ENG"
        issue = {
            "id": "i1", "identifier": "ENG-1", "title": "Ticket export to CSV", "description": state["description"], "url": "https://linear.app/acme/issue/ENG-1",
            "createdAt": "2026-10-01T09:00:00.000Z", "updatedAt": state["updated"], "completedAt": None, "canceledAt": None,
            "state": {"name": "In Progress", "type": "started"}, "labels": {"nodes": [{"name": "export"}]},
            "creator": {"id": "l1", "name": "Maya Rao", "displayName": "maya", "email": "maya@acme.io"},
            "assignee": {"id": "l2", "name": "Sam Kim", "displayName": "sam", "email": "sam@acme.io"},
            "comments": {"nodes": [{"id": "c1", "body": "Can we ship this Friday?", "createdAt": "2026-10-04T09:00:00.000Z", "url": "", "user": {"id": "l3", "name": "Lee Park", "displayName": "lee", "email": "lee@acme.io"}}]},
            "history": {"nodes": [{"createdAt": "2026-10-03T09:00:00.000Z", "updatedDescription": True, "actor": {"id": "l2", "name": "Sam Kim", "displayName": "sam", "email": "sam@acme.io"}}]},
        }  # fmt: skip
        return {"issues": {"nodes": [issue], "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    installs.set_team(org, linear={"token": "lin_api_x", "team": "ENG"})
    out = teamsync.sync_team(org, full=True, linear_query=query)
    assert not out["errors"], out["errors"]
    assert out["linear"]["tickets"] == 1 and out["linear"]["comments"] == 1
    times, actors = _in(org, lambda: get_graph().query("MATCH (t:Ticket {id: 'ENG-1'}) RETURN t.version_times, t.version_actors").result_set[0])
    assert actors == ["sam-kim"]  # the current text is dated to its last edit (Sam, Oct 3), not to the issue's creation
    assert {a["platform"] for p in _in(org, lambda: identity.directory(get_graph())) if p["id"] == "sam-kim" for a in p["accounts"]} == {"slack", "linear"}

    # Sam (the assignee) decides in Slack: drift on ENG-1; then the issue is edited in Linear and the drift closes
    r = _decide(org, "U2", "Decision: the export must support any date range up to 12 months, not only 30 days. ENG-1", "slack:C1:2.1")
    assert r["status"] == "drift" and r["ticket"] == "ENG-1", r
    state.update(
        description="Admins can export tickets for any date range up to 12 months as a CSV file (not only the last 30 days).",
        updated="2026-10-09T09:00:00.000Z",
    )
    out = teamsync.sync_team(org, linear_query=query)
    assert out["linear"]["new_versions"] == 1 and not out["errors"]
    assert _in(org, lambda: Q.drift(get_graph())) == []


def test_jira_and_linear_connect_from_the_team_page_without_showing_tokens(org, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app
    from connectors import jira, linear
    from pipeline import teamsync

    monkeypatch.setattr(jira, "check_project", lambda site, email, token, project: {"site": "https://acme.atlassian.net", "project": "ACME", "name": "Acme"})
    monkeypatch.setattr(linear, "check_team", lambda token, team: {"team": "ENG", "name": "Engineering"})
    monkeypatch.setattr(teamsync, "in_background", lambda *a, **k: None)
    with TestClient(app) as c:
        h = {"X-Org": org}
        assert (
            c.post("/api/team/jira", json={"site": "acme.atlassian.net", "email": "x@acme.io", "token": "jira-secret", "project": "acme"}, headers=h).json()[
                "project"
            ]
            == "ACME"
        )
        assert c.post("/api/team/linear", json={"token": "lin_api_secret", "team": "eng"}, headers=h).json()["team"] == "ENG"
        assert c.post("/api/team/linear", json={"team": "eng"}, headers=h).status_code == 200  # the saved key is kept
        st = c.get("/api/team", headers=h)
        assert st.json()["jira"]["project"] == "ACME" and st.json()["linear"]["team"] == "ENG"
        assert "jira-secret" not in st.text and "lin_api_secret" not in st.text
        assert c.post("/api/team/jira", json={"site": "x", "email": "y", "project": "Z"}, headers={"X-Org": "demo"}).status_code == 403


def test_adf_and_jira_times():
    from connectors.jira import adf_text, iso

    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Export "}, {"type": "mention", "attrs": {"text": "@Maya"}}]},
                                      {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "CSV"}]}]}]}]}  # fmt: skip
    assert adf_text(doc).strip() == "Export @Maya\n\n- CSV"
    assert iso("2026-10-01T09:00:00.000+0530") == "2026-10-01T03:30:00Z"
