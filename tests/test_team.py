"""A real team gets the demo's experience: their Slack people (names, titles, emails) and GitHub logins become one
person each, their GitHub issues and PRs become tickets and PRs, a decision in Slack by the ticket's owner raises the
same drift alert, and the graph keeps up as things change (an issue edit closes the drift; message edits and deletes,
people's new titles). Slack and GitHub are faked; FalkorDB is real."""

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
    {"id": "U1", "name": "maya.rao", "profile": {"real_name": "Maya Rao", "email": "maya@acme.io", "title": "Product Manager"}, "is_admin": True},
    {"id": "U2", "name": "sam", "profile": {"real_name": "Sam Kim", "email": "sam@acme.io", "title": "Backend Engineer"}},
    {"id": "U3", "name": "lee", "profile": {"real_name": "Lee Park", "email": "lee@acme.io", "title": "Support"}},
    {"id": "B1", "name": "somebot", "is_bot": True, "profile": {}},
]
GITHUB_PEOPLE = {"mayarao": {"name": "Maya Rao", "email": "maya@acme.io"}, "samk": {"name": "Sam Kim", "email": None}}
OLD = "Admins can export tickets created in the last 30 days as a CSV file."
NEW = "Admins can export tickets for any date range up to 12 months as a CSV file (not only the last 30 days)."


class FakeSlack:
    def users_list(self, **kw):
        return {"members": MEMBERS}

    def users_info(self, user):
        return {"user": next(m for m in MEMBERS if m["id"] == user)}

    def usergroups_list(self, **kw):
        return {"usergroups": [{"handle": "product", "users": ["U1"]}]}


@pytest.fixture()
def team(monkeypatch):
    from connectors import github_work, installs
    from pipeline import llm, teamsync

    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setenv("INSTALLS_PATH", str(Path(tmp.name) / "installs.json"))
    monkeypatch.setattr(llm, "available", lambda ttl=300.0: False)
    monkeypatch.setattr(teamsync, "_slack_client", lambda token: FakeSlack())
    org = installs.save_slack("T1", "Acme", "xoxb-test", "UBOT")["org"]
    installs.set_team(org, github={"repo": "acme/app", "token": "ghp-test"})
    body = {"text": OLD}

    def fake_get(path, token, **params):
        if path.endswith("/issues"):
            issue = {
                "number": 1, "title": "Ticket export to CSV", "body": body["text"], "state": "open", "labels": [{"name": "export"}],
                "user": {"login": "mayarao"}, "assignees": [{"login": "samk"}], "created_at": "2026-10-01T09:00:00Z",
                "updated_at": body.get("updated", "2026-10-01T09:00:00Z"), "closed_at": None, "html_url": "https://github.com/acme/app/issues/1",
            }  # fmt: skip
            pr = {
                "number": 2, "title": "Add CSV export endpoint", "body": "Fixes #1. Exports the last 30 days.", "state": "closed",
                "user": {"login": "samk"}, "created_at": "2026-10-03T09:00:00Z", "updated_at": "2026-10-05T09:00:00Z",
                "html_url": "https://github.com/acme/app/pull/2", "pull_request": {"merged_at": "2026-10-05T09:00:00Z"},
            }  # fmt: skip
            bot = {
                **pr,
                "number": 3,
                "title": "Bump requests",
                "body": "",
                "user": {"login": "dependabot[bot]", "type": "Bot"},
                "html_url": "https://github.com/acme/app/pull/3",
            }
            return [issue, pr, bot] if params.get("page", 1) == 1 else []
        if path.endswith("/issues/comments"):
            return []
        raise AssertionError(path)

    monkeypatch.setattr(github_work, "_get", fake_get)
    people = lambda login, token: GITHUB_PEOPLE[login]  # noqa: E731
    yield org, body, people
    if db.org_graph_name(org) in db.get_db().list_graphs():
        db.get_graph(db.org_graph_name(org)).delete()
    tmp.cleanup()


def _in(org, fn, *a, **kw):
    from graph.db import _org, set_org

    t = set_org(org)
    try:
        return fn(*a, **kw)
    finally:
        _org.reset(t)


def test_a_real_team_gets_the_same_drift_alert_and_it_stays_current(team):
    from connectors.slack import TeamPeople
    from graph import queries as Q
    from graph.db import get_graph
    from pipeline import identity, teamsync
    from pipeline.events import Event
    from pipeline.live import delete_message, edit_message, process_message

    org, body, people = team
    out = teamsync.sync_team(org, full=True, github_people=people)
    assert not out["errors"], out["errors"]
    assert out["people_from_slack"] == 3 and out["github"]["tickets"] == 1 and out["github"]["prs"] == 2
    who = {p["id"]: p for p in _in(org, lambda: identity.directory(get_graph()))}
    maya = who["maya-rao"]
    assert maya["role"] == "Product Manager" and {"admins", "product"} <= set(maya["groups"])
    assert {a["platform"] for a in maya["accounts"]} == {"slack", "github"}  # one person: matched by email
    assert {a["platform"] for a in who["sam-kim"]["accounts"]} == {"slack", "github"}  # matched by full name
    assert set(who) == {"maya-rao", "sam-kim", "lee-park"}  # three humans; dependabot is not a person

    # Maya created the issue, so her decision in Slack counts, exactly as for BD-101 in the demo
    author = _in(org, TeamPeople(FakeSlack()), "U1")
    msg = Event(source="slack", kind="message", id="slack:C1:100.1", author=author, ts="2026-10-08T10:00:00Z", channel="product",
                text="Decision: the export must support any date range up to 12 months, not only 30 days. GH-1")  # fmt: skip
    r = _in(org, process_message, msg)
    assert r["status"] == "drift" and r["ticket"] == "GH-1", r
    drift = _in(org, lambda: Q.drift(get_graph()))
    assert [d["ticket"] for d in drift] == ["GH-1"] and [p["pr"] for p in drift[0]["stale_prs"]] == [2]

    # someone who neither created nor is assigned the ticket can't change it (Lee is in support)
    lee = _in(org, TeamPeople(FakeSlack()), "U3")
    other = Event(source="slack", kind="message", id="slack:C1:100.2", author=lee, ts="2026-10-08T11:00:00Z", channel="product",
                  text="Decision: the export must also include attachments. GH-1")  # fmt: skip
    assert _in(org, process_message, other)["status"] == "no-decision-rights"

    # the issue is edited on GitHub to say what was decided: the next pass adds a version and the drift closes
    body.update(text=NEW, updated="2026-10-09T09:00:00Z")
    out = teamsync.sync_team(org, github_people=people)
    assert out["github"]["new_versions"] == 1 and not out["errors"]
    assert _in(org, lambda: Q.drift(get_graph())) == []

    # an edited message is checked again; a deleted one leaves the graph and the next pass re-derives
    edited = Event(source="slack", kind="message", id="slack:C1:100.2", author=lee, ts="2026-10-08T11:00:00Z", channel="product", text="never mind")
    _in(org, edit_message, edited)
    assert _in(org, lambda: get_graph().query("MATCH (m:Message {id: 'slack:C1:100.2'}) RETURN m.text").result_set) == [["never mind"]]
    assert _in(org, delete_message, "slack:C1:100.2")
    assert teamsync.sync_team(org, github_people=people)["resolved"]  # the dirty flag triggered a re-resolve


def test_people_follow_slack_and_can_be_merged_by_hand(team):
    from graph.db import get_graph
    from pipeline import identity, teamsync

    org, _, people = team
    teamsync.sync_team(org, full=True, github_people=people)
    MEMBERS[1]["profile"]["title"] = "Staff Engineer"  # a new title in Slack reaches the graph on the next pass
    try:
        teamsync.sync_team(org, github_people=people)
        assert {p["id"]: p["role"] for p in _in(org, lambda: identity.directory(get_graph()))}["sam-kim"] == "Staff Engineer"
    finally:
        MEMBERS[1]["profile"]["title"] = "Backend Engineer"
    _in(org, lambda: identity.set_person(get_graph(), "sam-kim", role="Tech Lead"))  # set by hand: kept over Slack's title
    teamsync.sync_team(org, github_people=people)
    assert {p["id"]: p["role"] for p in _in(org, lambda: identity.directory(get_graph()))}["sam-kim"] == "Tech Lead"
    out = _in(org, lambda: identity.merge(get_graph(), "maya-rao", "sam-kim"))
    ids = [p["id"] for p in _in(org, lambda: identity.directory(get_graph()))]
    assert out["relationships_moved"] > 0 and "sam-kim" not in ids and "maya-rao" in ids


def test_team_setup_api_is_only_for_team_graphs_and_never_shows_tokens(team, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app
    from connectors import github_work
    from pipeline import teamsync

    org, _, _ = team
    monkeypatch.setattr(github_work, "check_repo", lambda repo, token: {"repo": repo, "private": True})
    monkeypatch.setattr(teamsync, "in_background", lambda *a, **k: None)
    with TestClient(app) as c:
        assert c.get("/api/team").status_code == 403  # the demo company has no setup page
        assert c.post("/api/team/github", json={"repo": "acme/other", "token": "ghp-secret"}, headers={"X-Org": org}).json()["repo"] == "acme/other"
        st = c.get("/api/team", headers={"X-Org": org})
        assert st.json()["github"] == {"repo": "acme/other", "token_set": True, "since": None} and "ghp-secret" not in st.text
        assert st.json()["slack"]["team"] == "Acme"
