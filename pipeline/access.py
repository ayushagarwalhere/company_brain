"""Entity-level access control: who may see which node, enforced before anything reaches a person or a model.

Model
  * A node may carry `acl`: a list of grants. A grant is a group name ("hr", "leads") or "person:<id>".
    No `acl` (or an empty one) means everyone in the company may see it. Today Documents and their Chunks carry ACLs
    (from doc frontmatter `access:`, or from Google Drive sharing); the same check works for any label.
  * A person's grants: their `groups` (people.json), "person:<id>", and "everyone". A restricted doc's ACL always
    includes "person:<author>", added when it is written, so authors keep seeing their own docs.
  * The viewer is per request: the API's X-User header (in production: the SSO identity), the chat user for bots,
    the actor for CLI calls. No viewer = anonymous = only unrestricted nodes.

Enforcement, in depth (a single miss shouldn't leak):
  1. In the query: search_knowledge filters chunks by ACL inside the vector query itself.
  2. In every agent tool (agent.tools.call): rows and evidence paths that mention a node the viewer can't see are
     dropped before the LLM or the rules agent ever reads them, so a model can't leak what it never received.
  3. On every API response (api/main.py middleware): the same redaction over the JSON body.
Nothing says that a hidden node exists: no counts, no "restricted" markers in results.
"""

import json
from contextvars import ContextVar

_viewer: ContextVar[str | None] = ContextVar("viewer", default=None)


def set_viewer(person: str | None):
    """Sets the person the current request acts for; returns a token for reset()."""
    return _viewer.set(person or None)


def reset_viewer(token) -> None:
    _viewer.reset(token)


def current_viewer() -> str | None:
    return _viewer.get()


def grants(g, person: str | None) -> list[str]:
    """Everything that can unlock a node for this person."""
    if not person:
        return ["everyone"]
    try:
        rows = g.ro_query("MATCH (p:Person {id: $p}) RETURN coalesce(p.groups, []), p.email", {"p": person}).result_set
    except Exception:  # noqa: BLE001 - the org's graph doesn't exist yet
        rows = []
    if not rows:
        return ["everyone", f"person:{person}"]
    groups, email = rows[0]
    return ["everyone", f"person:{person}"] + list(groups) + ([f"email:{email.lower()}"] if email else [])


# A node is visible when it has no ACL or the viewer holds one of its grants (as a Cypher predicate on `n`).
VISIBLE = "(n.acl IS NULL OR size(n.acl) = 0 OR any(x IN n.acl WHERE x IN $grants))"


def hidden(g, person: str | None) -> dict[str, list[str]]:
    """{"ids": [...], "titles": [...]} of restricted nodes this person may NOT see (what redaction looks for)."""
    try:
        g.ro_query("RETURN 1")
    except Exception:  # noqa: BLE001 - the org's graph doesn't exist yet: nothing in it to hide
        return {"ids": [], "titles": []}
    rows = g.ro_query(
        # ACLs live on Documents; a chunk's id starts with its document's id, so hiding the doc id hides its chunks too
        f"""MATCH (n:Document) WHERE n.acl IS NOT NULL AND size(n.acl) > 0 AND NOT {VISIBLE}
            RETURN n.id, n.title""",
        {"grants": grants(g, person)},
    ).result_set
    return {"ids": sorted({r[0] for r in rows if r[0]}), "titles": sorted({r[1] for r in rows if r[1]})}


def _tokens(h: dict) -> list[str]:
    toks = list(h["ids"]) + [t for t in h["titles"] if len(t) >= 6]
    # chunk ids are "<doc id>#<n>": the doc id already covers them in text
    return sorted(set(toks), key=len, reverse=True)


def _mentions(obj, toks: list[str]) -> bool:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return any(t in text for t in toks)


def redact(obj, h: dict):
    """Removes every list element (row, path, hit) that mentions a hidden node; a top-level string that mentions one
    is replaced. Dict values are recursed into, so nested lists are cleaned too."""
    toks = _tokens(h)
    if not toks:
        return obj

    def walk(x):
        if isinstance(x, list):
            return [walk(v) for v in x if not _mentions(v, toks)]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, str) and _mentions(x, toks):
            return "I don't have information on that you can access."
        return x

    return walk(obj)
