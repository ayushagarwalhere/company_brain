"""A missed IMPLEMENTS judgment must not turn shipped work into a false drift alert.

One ticket, one chat decision by its owner (10 -> 100 entries), PR-1 merged BEFORE the decision (old
version) and PR-2 merged AFTER it, delivering the new version. The ticket text is never updated, so
only IMPLEMENTS can tell the decision shipped.
"""

from datetime import UTC, datetime, timedelta

import pytest

from graph.db import get_db, get_graph
from graph.queries import drift
from pipeline.events import Event
from pipeline.extract import HeuristicExtractor


def _up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
GRAPH = "test_implements_fallback"
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


class NoImplements(HeuristicExtractor):
    """An extractor that never judges a PR to implement anything (what qwen3:8b did on the demo)."""

    def implements(self, pr, candidates):
        return []


def _build(monkeypatch, extractor, ablate=frozenset()):
    from graph import writer
    from pipeline import resolve as R

    g = get_graph(GRAPH)
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass
    g = get_graph(GRAPH)
    writer.apply_schema(g)
    writer.write_people(g, [{"id": p, "name": p, "role": "engineer"} for p in ("own", "cust")])
    v1 = "The alpha report must include the last 10 entries for admins."
    tk = lambda tid, title, labels, text: Event(
        "tickets",
        "ticket",
        tid,
        "own",
        iso(T0),
        f"{title}\n\n{text}",
        extra={  # noqa: E731
            "title": title,
            "description": text,
            "state": "In Progress",
            "labels": labels,
            "assignee": "own",
            "sprint": None,
            "updated_at": iso(T0),
            "completed_at": None,
            "versions": [{"at": iso(T0), "to": text, "actor": "own"}],
        },
    )
    writer.write_tickets(
        g,
        [
            tk("SC-0", "alpha report", ["alpha", "backend"], v1),
            tk("SC-1", "alpha report export button", ["alpha", "frontend"], "Work on the alpha report export button."),
        ],
    )
    writer.write_messages(
        g,
        [
            Event(
                "slack",
                "message",
                "m_root",
                "cust",
                iso(T0 + timedelta(days=2)),
                "Customers keep asking about the alpha report, the last 10 entries is not enough.",
                channel="product",
            ),
            Event(
                "slack",
                "message",
                "m_dec",
                "own",
                iso(T0 + timedelta(days=3)),
                "Decision: the alpha report must include the last 100 entries, for admins and managers.",
                channel="product",
                thread_of="m_root",
            ),
        ],
    )
    pr = lambda n, title, body, created, merged: Event(
        "github",
        "pull_request",
        f"PR-{n}",
        "own",
        iso(created),
        f"{title}\n\n{body}",
        extra={  # noqa: E731
            "number": n,
            "title": title,
            "body": body,
            "state": "merged",
            "merged_at": iso(merged),
        },
    )
    writer.write_pull_requests(
        g,
        [
            pr(1, "SC-0: alpha report", "Fixes SC-0. Shows the last 10 entries for admins.", T0 + timedelta(days=1), T0 + timedelta(days=1, hours=6)),
            pr(
                2,
                "SC-0: alpha report for managers",
                "Fixes SC-0. Shows the last 100 entries for admins and managers.",
                T0 + timedelta(days=5),
                T0 + timedelta(days=6),
            ),
        ],
    )
    monkeypatch.setattr(R, "get_extractor", lambda name: extractor)
    R.resolve(g, "heuristic", log=lambda *_: None, ablate=ablate)
    return g


def _impl(g):
    return {tuple(r) for r in g.query("MATCH (p:PullRequest)-[e:IMPLEMENTS]->(q:Requirement) RETURN p.id, q.id, coalesce(e.via, 'extractor')").result_set}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    try:
        get_graph(GRAPH).delete()
    except Exception:  # noqa: BLE001
        pass


def test_without_the_fallback_a_missed_implements_is_a_false_drift(monkeypatch):
    g = _build(monkeypatch, NoImplements(), ablate=frozenset({"implements_fallback"}))
    assert [d["ticket"] for d in drift(g)] == ["SC-0"]  # the reproduction: PR-2 shipped it, yet it's flagged


def test_time_aware_fallback_links_the_pr_merged_after_the_decision(monkeypatch):
    g = _build(monkeypatch, NoImplements())
    assert drift(g) == []
    impl = _impl(g)
    assert ("PR-2", "req:m_dec", "time+semantic") in impl
    assert not any(p == "PR-1" and q == "req:m_dec" for p, q, _ in impl)  # merged before the decision: cannot implement it


def test_extractor_implements_stays_primary(monkeypatch):
    g = _build(monkeypatch, HeuristicExtractor())
    assert drift(g) == []
    assert ("PR-2", "req:m_dec", "extractor") in _impl(g)
