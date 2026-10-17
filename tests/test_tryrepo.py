"""Try it on your own repo (pipeline/tryrepo.py): a public repo's issues, PRs and comments into a graph of its own, and
what the graph shows. GitHub is faked; FalkorDB is real."""

import tempfile
import time
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

REPO = "acme/widgets"
U = {"maya": {"login": "maya", "type": "User"}, "sam": {"login": "sam", "type": "User"}, "lee": {"login": "lee", "type": "User"},
     "bot": {"login": "ci-helper[bot]", "type": "Bot"}}  # fmt: skip


def issue(n, title, body, user, labels=(), state="open", assignee=None, comments=0):
    return {
        "number": n, "title": title, "body": body, "state": state, "labels": [{"name": x} for x in labels], "assignees": [U[assignee]] if assignee else [],
        "user": U[user], "created_at": f"2026-10-0{n % 9 + 1}T09:00:00Z", "updated_at": f"2026-10-1{n % 9}T09:00:00Z", "closed_at": None,
        "html_url": f"https://github.com/{REPO}/issues/{n}", "comments": comments,
    }  # fmt: skip


def pull(n, title, body, user, merged=True):
    return {
        "number": n, "title": title, "body": body, "state": "closed" if merged else "open", "labels": [], "assignees": [], "user": U[user],
        "created_at": "2026-10-12T09:00:00Z", "updated_at": "2026-10-13T09:00:00Z", "closed_at": None, "merged_at": "2026-10-13T09:00:00Z" if merged else None,
        "html_url": f"https://github.com/{REPO}/pull/{n}",
    }  # fmt: skip


def comment(cid, n, user, body, kind="issues"):
    return {"id": cid, "issue_url": f"https://api.github.com/repos/{REPO}/issues/{n}", "user": U[user], "body": body, "created_at": "2026-10-14T09:00:00Z",
            "html_url": f"https://github.com/{REPO}/{kind}/{n}#issuecomment-{cid}"}  # fmt: skip


ISSUES = [
    issue(1, "Export tickets to CSV", "Admins can export the last 30 days of tickets as CSV.", "maya", ["export"], assignee="sam", comments=2),
    issue(2, "Dark mode for the dashboard", "Add a dark theme.", "lee", ["ui"], comments=5),
    issue(4, "Export is slow for big accounts", "Exports time out above 50k tickets.", "lee", ["export"]),
    {**issue(5, "Bump deps", "", "bot"), "pull_request": {"merged_at": None}},  # a PR, as /issues lists it: skipped there
]
PULLS = [
    pull(3, "CSV export endpoint", "Fixes #1", "sam"),
    pull(6, "Speed up export queries", "Part of #4. See also #9.", "sam", merged=False),
    pull(7, "deps", "", "bot"),
]
OLD = issue(9, "Export API docs", "Document the export endpoint.", "maya", ["docs"], state="closed")
COMMENTS = [
    comment(10, 1, "maya", "Decision: the export must support any date range up to 12 months, not only the last 30 days."),
    comment(11, 2, "lee", "Any update on this? Customers keep asking."),
    comment(12, 3, "lee", "Looks good to me.", "pull"),
    comment(13, 1, "bot", "Coverage report: 91%."),
]


def fake_gh(private=False, calls=None):
    def gh(path, **params):
        (calls if calls is not None else []).append(path)
        if path == f"/repos/{REPO}":
            return {"full_name": REPO, "private": private, "visibility": "private" if private else "public", "description": "Widgets", "stargazers_count": 3}
        if path.endswith("/issues/comments"):
            return COMMENTS
        if path.endswith("/issues/9"):
            return OLD
        if path.endswith("/issues"):
            return ISSUES if params.get("page") == 1 else []
        if path.endswith("/pulls"):
            return PULLS
        raise AssertionError(path)

    return gh


@pytest.fixture()
def tr(monkeypatch):
    from pipeline import tryrepo

    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setattr(tryrepo, "CACHE", Path(tmp.name))
    monkeypatch.setattr(tryrepo, "_gh", fake_gh())
    monkeypatch.setattr(tryrepo, "_token", lambda: "t")  # with a token, the PR-referenced issue #9 is fetched too
    tryrepo._jobs.clear()
    yield tryrepo
    name = db.org_graph_name(tryrepo.org_for(REPO))
    if name in db.get_db().list_graphs():
        db.get_graph(name).delete()
    tryrepo._jobs.clear()
    tmp.cleanup()


def test_parse_and_org_ids():
    from pipeline.tryrepo import TryError, org_for, parse

    assert parse("https://github.com/FalkorDB/FalkorDB/issues?q=x") == "FalkorDB/FalkorDB"
    assert parse(" github.com/acme/widgets.git/ ") == "acme/widgets"
    assert parse("acme/widgets") == "acme/widgets"
    for bad in ("acme", "acme/widgets/extra", "../etc/passwd", "-acme/x", ""):
        with pytest.raises(TryError):
            parse(bad)
    assert org_for("FalkorDB/FalkorDB") == "gh-falkordb-falkordb"
    long = org_for("some-very-long-organisation-name/an-even-longer-repository-name")
    assert db.ORG_RE.match(long) and long.startswith("gh-") and len(long) <= 40


def test_a_repo_becomes_a_graph_of_who_knows_what_chains_and_open_work(tr):
    snap = tr.fetch(REPO)
    assert {i["number"] for i in snap["issues"]} == {1, 2, 4, 9, 3, 6}  # bots and /issues' PR copy left out; #9 fetched for PR #6
    assert all(c["user"] != "ci-helper[bot]" for c in snap["comments"])
    out = tr.build(snap, tr.org_for(REPO))
    assert {(c["issue"], c["pr"]) for c in out["chains"]} >= {("GH-1", 3), ("GH-4", 6), ("GH-9", 6)}
    assert {p["person"] for p in out["people"]} == {"maya", "sam", "lee"}
    sam = next(p for p in out["people"] if p["person"] == "sam")
    assert sam["prs"] == 2 and sam["merged"] == 1 and sam["assigned"] == 1
    assert next(p for p in out["people"] if p["person"] == "lee")["reviews"] == 1  # commented on PR #3
    export = next(a for a in out["areas"] if a["label"] == "export")
    assert export["issues"] == 2 and export["people"][0]["person"] == "sam"  # wrote the PRs for both export issues
    assert [t["issue"] for t in out["no_pr"]] == ["GH-2"]  # the only open issue no PR names
    assert out["counts"]["open_no_pr"] == 1 and out["graph"]["nodes"] and "precision" in out["note"]
    # the issue author's explicit decision in a comment: a candidate decision, and drift (the body still says 30 days)
    assert [(d["issue"], d["by"]) for d in out["decisions"]] == [("GH-1", "maya")]
    assert [d["issue"] for d in out["drift"]] == ["GH-1"]


def test_private_repos_are_refused_even_when_the_token_could_read_them(tr, monkeypatch):
    monkeypatch.setattr(tr, "_gh", fake_gh(private=True))
    with pytest.raises(tr.TryError, match="private"):
        tr.fetch(REPO)


def test_the_api_builds_once_then_serves_the_cache_and_keeps_the_graph_read_only(tr):
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        first = c.post("/api/try", json={"repo": f"https://github.com/{REPO}"}).json()
        assert first["state"] in ("queued", "running", "ready") and first["org"] == "gh-acme-widgets"
        for _ in range(100):
            st = c.get("/api/try/status", params={"repo": REPO}).json()
            if st["state"] in ("ready", "error"):
                break
            time.sleep(0.1)
        assert st["state"] == "ready", st
        assert st["result"]["counts"]["chains"] >= 3
        calls: list[str] = []
        tr._gh = fake_gh(calls=calls)
        again = c.post("/api/try", json={"repo": REPO}).json()
        assert again["state"] == "ready" and calls == []  # cached: no GitHub call
        assert [r["repo"] for r in c.get("/api/try/recent").json()["repos"]] == [REPO]
        assert c.post("/api/try", json={"repo": "not a repo"}).status_code == 400
        h = {"X-Org": "gh-acme-widgets"}
        assert c.get("/api/drift", headers=h).status_code == 200  # the full dashboard reads it
        assert c.post("/api/drift/dismiss", json={"requirement": "x", "actor": "maya"}, headers=h).status_code == 403
        assert c.post("/api/orgs/gh-acme-widgets/bootstrap").status_code == 403  # never replaced with demo data
