"""Who is who: one Person per human, whichever systems they show up in.

    (Person {id, name, role, email, groups})-[:HAS_ACCOUNT {via}]->(Account {id: "slack:U123", platform, handle, name, email, title})

resolve() turns an account (a Slack user, a Discord member, a GitHub login) into a person id:
  1. the account is already known: its person;
  2. else a person with the same email (case-insensitive);
  3. else a person whose full name (two words or more) normalises to the same string;
  4. else a person with an account on another platform whose handle normalises to the same string
     (GitHub "maya-chen" and Slack "maya.chen"), or whose name does ("mayachen" and "Maya Chen");
  5. else a new person.
The rule that matched is kept on the HAS_ACCOUNT edge (`via`), so the team's "Who's who" page shows which links were
inferred, and merge() fixes a missed match by hand. Every account write is idempotent.

Roles and groups come from the systems that know them: a Slack profile's title, a Discord member's top role; Slack
admins and user groups, Discord roles become `groups` (they decide who may see restricted documents). A role or group
set by hand on the Who's who page is never overwritten by a sync.

Used only for connected teams' graphs; the demo company keeps its hand-written people.json.
"""

import re

from graph import queries as Q

GENERIC = {"admin", "user", "test", "bot", "team", "info", "support", "dev"}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "person"


def _keys(name: str | None, handle: str | None) -> set[str]:
    out = {norm(handle)}
    if name and len(name.split()) >= 2:
        out.add(norm(name))
    return {k for k in out if len(k) >= 4 and k not in GENERIC}


def _match(g, platform: str, name: str | None, handle: str | None, email: str | None) -> tuple[str | None, str]:
    if email:
        rows = Q.rows(g, "MATCH (p:Person) WHERE toLower(p.email) = $e RETURN p.id AS id LIMIT 1", e=email.lower())
        if rows:
            return rows[0]["id"], "email"
    keys = _keys(name, handle)
    if not keys:
        return None, "new"
    for r in Q.rows(
        g,
        """MATCH (p:Person) OPTIONAL MATCH (p)-[:HAS_ACCOUNT]->(a:Account) WHERE a.platform <> $platform
           RETURN p.id AS id, p.name AS name, collect(a.handle) AS handles, collect(a.name) AS names""",
        platform=platform,
    ):
        theirs = _keys(r["name"], None) | {k for h in r["handles"] for k in _keys(None, h)} | {k for n in r["names"] for k in _keys(n, None)}
        if keys & theirs:
            return r["id"], "name" if norm(name) in theirs else "handle"
    return None, "new"


def resolve(
    g,
    platform: str,
    account_id: str,
    handle: str | None,
    name: str | None = None,
    email: str | None = None,
    title: str | None = None,
    groups: list[str] | None = None,
) -> str:
    """The person behind an account, creating or linking as needed; keeps the account's details current."""
    known = Q.rows(g, "MATCH (p:Person)-[:HAS_ACCOUNT]->(:Account {id: $a}) RETURN p.id AS id", a=account_id)
    if known:
        pid, via = known[0]["id"], None
    else:
        pid, via = _match(g, platform, name, handle, email)
        if not pid:
            base = slug(name or handle)
            pid, n = base, 1
            while Q.rows(g, "MATCH (p:Person {id: $id}) RETURN 1 AS x", id=pid):
                n += 1
                pid = f"{base}-{n}"
            g.query("CREATE (:Person {id: $id})", {"id": pid})
    g.query(
        """MATCH (p:Person {id: $pid})
           MERGE (a:Account {id: $aid})
           SET a.platform = $platform, a.handle = $handle, a.name = $name, a.email = $email, a.title = $title
           MERGE (p)-[h:HAS_ACCOUNT]->(a)
           SET h.via = coalesce(h.via, $via)
           SET p.name = coalesce(p.name, $name, $handle), p.email = coalesce(p.email, $email),
               p.role = CASE WHEN p.role_manual THEN p.role ELSE coalesce($title, p.role) END""",
        {"pid": pid, "aid": account_id, "platform": platform, "handle": handle, "name": name, "email": email, "title": title or None, "via": via or "account"},
    )
    if groups is not None:  # groups from this platform replace this platform's previous groups; manual ones stay
        g.query(
            """MATCH (p:Person {id: $pid})-[:HAS_ACCOUNT]->(a:Account {id: $aid})
               WITH p, a, coalesce(a.groups, []) AS old
               SET a.groups = $groups,
                   p.groups = [x IN coalesce(p.groups, []) WHERE NOT x IN old OR x IN coalesce(p.manual_groups, [])] + [x IN $groups WHERE NOT x IN coalesce(p.groups, [])]""",
            {"pid": pid, "aid": account_id, "groups": sorted(set(groups))},
        )
    return pid


def merge(g, keep: str, drop: str) -> dict:
    """Merges two people found to be one human: every relationship and account of `drop` moves to `keep`."""
    if keep == drop:
        raise ValueError("pick two different people")
    for pid in (keep, drop):
        if not Q.rows(g, "MATCH (p:Person {id: $id}) RETURN 1 AS x", id=pid):
            raise ValueError(f"unknown person {pid}")
    moved = 0
    accounts = [r["a"] for r in Q.rows(g, "MATCH (:Person {id: $d})-[:HAS_ACCOUNT]->(a:Account) RETURN a.id AS a", d=drop)]
    for t in [r["t"] for r in Q.rows(g, "MATCH (:Person {id: $d})-[r]->() RETURN DISTINCT type(r) AS t", d=drop)]:
        assert re.fullmatch(r"[A-Z_]+", t), t
        moved += Q.rows(
            g,
            f"MATCH (d:Person {{id: $d}})-[r:{t}]->(x), (k:Person {{id: $k}}) MERGE (k)-[n:{t}]->(x) SET n += properties(r) DELETE r RETURN count(*) AS n",
            d=drop,
            k=keep,
        )[0]["n"]
    for t in [r["t"] for r in Q.rows(g, "MATCH ()-[r]->(:Person {id: $d}) RETURN DISTINCT type(r) AS t", d=drop)]:
        assert re.fullmatch(r"[A-Z_]+", t), t
        moved += Q.rows(
            g,
            f"MATCH (x)-[r:{t}]->(d:Person {{id: $d}}), (k:Person {{id: $k}}) MERGE (x)-[n:{t}]->(k) SET n += properties(r) DELETE r RETURN count(*) AS n",
            d=drop,
            k=keep,
        )[0]["n"]
    g.query(
        """MATCH (k:Person {id: $k}), (d:Person {id: $d})
           SET k.name = coalesce(k.name, d.name), k.email = coalesce(k.email, d.email), k.role = coalesce(k.role, d.role),
               k.groups = coalesce(k.groups, []) + [x IN coalesce(d.groups, []) WHERE NOT x IN coalesce(k.groups, [])]""",
        {"k": keep, "d": drop},
    )
    g.query("MATCH (:Person {id: $k})-[h:HAS_ACCOUNT]->(a:Account) WHERE a.id IN $ids SET h.via = 'merged by hand'", {"k": keep, "ids": accounts})
    g.query("MATCH (d:Person {id: $d}) DETACH DELETE d", {"d": drop})
    return {"kept": keep, "merged": drop, "relationships_moved": moved}


def set_person(g, pid: str, role: str | None = None, groups: list[str] | None = None) -> None:
    """A role or groups set by hand: kept over whatever the systems say later."""
    if role is not None:
        g.query("MATCH (p:Person {id: $id}) SET p.role = $r, p.role_manual = true", {"id": pid, "r": role})
    if groups is not None:
        g.query("MATCH (p:Person {id: $id}) SET p.groups = $g, p.manual_groups = $g", {"id": pid, "g": sorted(set(groups))})


def directory(g) -> list[dict]:
    """The Who's who page: each person, role, groups, accounts (with how each was linked) and how much they appear."""
    rows = Q.rows(
        g,
        """MATCH (p:Person) WHERE NOT p.id STARTS WITH 'bot:' AND p.id <> 'unknown'
           OPTIONAL MATCH (p)-[h:HAS_ACCOUNT]->(a:Account)
           WITH p, collect(CASE WHEN a IS NULL THEN NULL ELSE {platform: a.platform, handle: a.handle, name: a.name, title: a.title, via: h.via} END) AS accounts
           OPTIONAL MATCH (p)-[w]-(x) WHERE x:Message OR x:Ticket OR x:PullRequest
           RETURN p.id AS id, p.name AS name, p.role AS role, p.email AS email, coalesce(p.groups, []) AS groups, accounts, count(w) AS activity
           ORDER BY activity DESC, id""",
    )
    for r in rows:
        r["accounts"] = [a for a in r["accounts"] if a]
    return rows
