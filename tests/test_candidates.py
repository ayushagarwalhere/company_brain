"""A change by a non-owner on a GUESSED ticket is kept as an unverified candidate, never as drift."""

from datetime import UTC, datetime, timedelta

import pytest

from graph import queries as Q
from graph.db import get_db, get_graph
from pipeline.events import Event


def _up():
    try:
        get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
GRAPH = "test_candidates"
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def _build(keep_candidates=True):
    from graph import writer
    from pipeline.resolve import resolve

    g = get_graph(GRAPH)
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass
    g = get_graph(GRAPH)
    writer.apply_schema(g)
    writer.write_people(g, [{"id": p, "name": p, "role": "engineer"} for p in ("own", "lead")])
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
            tk("SC-0", "alpha audit report", ["alpha", "backend"], "The alpha audit report must include the last 10 entries for admins."),
            tk("SC-1", "alpha export button", ["alpha", "frontend"], "Add an export button to the alpha list."),
        ],
    )
    writer.write_messages(
        g,
        [
            # no ticket id anywhere: the ticket is a TF-IDF guess, and 'lead' owns neither ticket
            Event(
                "slack",
                "message",
                "m_guess",
                "lead",
                iso(T0 + timedelta(days=2)),
                "Decision: the alpha audit report must include the last 50 entries for auditors and admins.",
                channel="product",
            ),
            # explicit ticket id, still not an owner: dropped as before
            Event(
                "slack",
                "message",
                "m_named",
                "lead",
                iso(T0 + timedelta(days=3)),
                "Decision: SC-0 must include the last 60 entries for auditors and admins.",
                channel="product",
            ),
        ],
    )
    resolve(g, "heuristic", log=lambda *_: None, keep_candidates=keep_candidates)
    return g


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    get_graph(GRAPH).delete()


def test_guessed_ticket_without_rights_becomes_an_unverified_candidate():
    g = _build()
    assert Q.drift(g) == []
    rows = Q.rows(g, Q.UNVERIFIED_CHANGES)
    assert [(r["message"], r["ticket"], r["author"]) for r in rows] == [("m_guess", "SC-0", "lead")]
    chain = g.query("MATCH (q:Requirement) WHERE q.status = 'candidate' MATCH (q)-[r:SUPERSEDES|AMENDS]-() RETURN count(r)").result_set[0][0]
    assert chain == 0  # candidates never enter the version chain or the drift path


def test_without_candidates_it_is_dropped():
    g = _build(keep_candidates=False)
    assert Q.rows(g, Q.UNVERIFIED_CHANGES) == []
