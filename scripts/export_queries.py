"""Generates docs/QUERIES.md from graph/queries.py, so the submitted query list can't drift from the code.

python -m scripts.export_queries
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "graph" / "queries.py"
OUT = ROOT / "docs" / "QUERIES.md"
SEARCH_DIRS = ["agent", "api", "bots", "pipeline", "graph", "benchmark"]


def main():
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    queries = []
    import graph.queries as module  # final values, including queries assembled from shared fragments (WEIGHT_EXPR)

    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.isupper()
            and isinstance(getattr(module, node.targets[0].id, None), str)
            and node.targets[0].id != "WEIGHT_EXPR"
        ):
            name = node.targets[0].id
            comment, i = [], node.lineno - 2
            while i >= 0 and lines[i].lstrip().startswith("#"):
                comment.insert(0, lines[i].lstrip("# ").rstrip())
                i -= 1
            pattern = rf"\bQ\.{name}\b|\bqueries\.{name}\b"
            if name == "DRIFT":  # mostly called through the drift() helper
                pattern += r"|\bQ\.drift\(|\bimport drift\b|\bdrift\(g"
            used = sorted(
                {
                    str(p.relative_to(ROOT)).replace("\\", "/")
                    for d in SEARCH_DIRS
                    for p in (ROOT / d).rglob("*.py")
                    if p != SRC and re.search(pattern, p.read_text(encoding="utf-8"))
                }
            )
            queries.append((name, " ".join(comment), getattr(module, name).strip(), used))

    doc = ast.get_docstring(tree) or ""
    out = [
        "# Cypher queries the product depends on",
        "",
        "_Generated from [`graph/queries.py`](../graph/queries.py) by `python -m scripts.export_queries`._",
        "",
        "Run them in the FalkorDB Browser (http://localhost:3001) against the `company_brain` graph; " "parameters are written `$name`.",
        "",
        "## Drift, in words",
        "",
        "```",
        doc.strip(),
        "```",
        "",
    ]
    out += ["## Index", ""] + [f"- [`{n}`](#{n.lower()}): {c or ''}".rstrip(": ") for n, c, _, _ in queries] + [""]
    for name, comment, q, used in queries:
        out += [f"## {name}", ""]
        if comment:
            out += [comment, ""]
        out += ["```cypher", q, "```", ""]
        if used:
            out += ["Used by: " + ", ".join(f"[`{u}`](../{u})" for u in used), ""]
    out += [
        "## Also used",
        "",
        "- **Full-text search** ([`graph/explore.py`](../graph/explore.py)): "
        "`CALL db.idx.fulltext.createNodeIndex('Message', 'text')` (plus Ticket, PullRequest, Person) and "
        "`CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score`.",
        "- **Writes** ([`graph/writer.py`](../graph/writer.py), [`pipeline/resolve.py`](../pipeline/resolve.py), "
        "[`pipeline/actions.py`](../pipeline/actions.py)): every node is `MERGE`d on `id` (idempotent re-ingest); "
        "resolution edges carry `via` so each link records how it was made.",
        "- **Graph algorithm**: the connection tool uses `algo.SPpaths` with `relDirection: 'both'`, because Cypher "
        "`shortestPath` is directed-only in FalkorDB (see [`EXPLAIN.md`](EXPLAIN.md)).",
        "",
    ]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(queries)} queries)")


if __name__ == "__main__":
    main()
