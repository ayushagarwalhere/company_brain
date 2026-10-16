"""Regression test: large reads must page, or FalkorDB's result-set cap silently truncates them.

The scale test (benchmark/scale.py) found this: at 20k+ messages the resolver only saw the first
10,000 (RESULTSET_SIZE in the Docker image), and 30% of planted drifts were missed.
"""
import pytest

from graph import db

GRAPH = "test_paging"


def _up():
    try:
        db.get_db().list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _up(), reason="FalkorDB not reachable")
def test_rows_paged_returns_everything_in_order():
    from pipeline.resolve import _rows_paged
    g = db.get_graph(GRAPH)
    try:
        g.query("UNWIND range(1, 12345) AS i CREATE (:Row {i: i})")
        out = _rows_paged(g, "MATCH (r:Row) RETURN r.i AS i ORDER BY i", page=5000)
        assert len(out) == 12345
        assert [r["i"] for r in out[:3]] == [1, 2, 3] and out[-1]["i"] == 12345
    finally:
        g.delete()
