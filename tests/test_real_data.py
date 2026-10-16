"""The real-data adapter and label scoring (no network, no FalkorDB)."""

import json
import tempfile
from pathlib import Path

from benchmark.real_data import gh_ids, score, to_events


def _snap():
    issue = {
        "number": 7,
        "title": "Export",
        "body": "See #3 and owner/repo#9",
        "state": "open",
        "labels": ["export"],
        "assignees": ["ann"],
        "user": "bob",
        "created_at": "2026-01-01T00:00:00Z",
        "closed_at": None,
        "html_url": "https://github.com/o/r/issues/7",
        "merged_at": None,
        "is_pr": False,
    }
    pr = {
        **issue,
        "number": 8,
        "title": "Fix export",
        "body": "fixes #7",
        "html_url": "https://github.com/o/r/pull/8",
        "merged_at": "2026-01-02T00:00:00Z",
        "is_pr": True,
    }
    comments = [
        {
            "id": 1,
            "issue_url": "https://api.github.com/repos/o/r/issues/7",
            "user": "ann",
            "body": "dup of #3",
            "created_at": "2026-01-01T01:00:00Z",
            "html_url": "u1",
        },
        {
            "id": 2,
            "issue_url": "https://api.github.com/repos/o/r/issues/8",
            "user": "ann",
            "body": "LGTM",
            "created_at": "2026-01-01T02:00:00Z",
            "html_url": "u2",
        },
    ]
    return {"issues": [issue, pr], "comments": comments}


def test_hash_refs_become_ticket_ids_but_cross_repo_refs_do_not():
    assert gh_ids("fixes #12, see o/r#5 and &#39;") == "fixes GH-12, see o/r#5 and &#39;"


def test_adapter_maps_issues_comments_and_prs_and_drops_pr_comments():
    tickets, messages, prs = to_events(_snap())
    assert [t.id for t in tickets] == ["GH-7"] and tickets[0].extra["assignee"] == "ann"
    assert [m.id for m in messages] == ["ghc:1"] and messages[0].extra["issue"] == "GH-7"
    assert prs[0].id == "PR-8" and prs[0].extra["state"] == "merged" and prs[0].ticket_refs == ["GH-7"]


def test_score_reports_precision_and_patterns_per_set():
    labels = {
        "labels": [
            {"set": "a", "verdict": "false_positive", "pattern": "bot"},
            {"set": "a", "verdict": "true_drift", "pattern": None},
            {"set": "b", "verdict": "false_positive", "pattern": "status"},
        ]
    }
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "labels.json"
        p.write_text(json.dumps(labels), encoding="utf-8")
        out = score(p)
    assert out["a"]["precision"] == 0.5 and out["a"]["failure_patterns"] == {"bot": 1}
    assert out["all"]["labelled"] == 3 and out["all"]["true_positive"] == 1
