"""What every work connector (GitHub issues, Jira, Linear) shares: people through pipeline.identity, ticket versions,
and one way of writing tickets, their discussion and pull requests into the graph.

A tracker's ticket becomes the same Ticket the demo's tickets are: title, description, state, labels, creator,
assignee and every known description version (who wrote it, when). Its comments become Messages that MENTION it, so a
decision made in a comment counts like one made in chat. PRs stay GitHub's: "Fixes ENG-12" links a PR to a Linear
ticket the same way "Fixes BD-101" does in the demo.
"""

from collections.abc import Callable

from pipeline.events import Event, from_ms


class People:
    """Account -> Person for one pass: a known account is looked up; a new one is resolved (and matched to the same
    human's other accounts) by pipeline.identity."""

    def __init__(self, g, platform: str):
        self.g, self.platform, self.cache = g, platform, {}

    def __call__(
        self, account_id: str | None, handle: str | None = None, name: str | None = None, email: str | None = None, details: Callable | None = None
    ) -> str | None:
        from pipeline import identity

        if not account_id:
            return None
        key = f"{self.platform}:{account_id}"
        if key not in self.cache:
            known = self.g.query("MATCH (p:Person)-[:HAS_ACCOUNT]->(:Account {id: $a}) RETURN p.id", {"a": key}).result_set
            if known:
                self.cache[key] = known[0][0]
            else:
                d = details() if details else {}
                self.cache[key] = identity.resolve(self.g, self.platform, key, handle, d.get("name") or name, d.get("email") or email)
        return self.cache[key]

    @property
    def count(self) -> int:
        return len(set(self.cache.values()))


def stored_versions(g, ids: list[str]) -> dict[str, list[dict]]:
    """The description versions already in the graph, per ticket: [{"to", "at", "actor"}]."""
    out = {}
    for tid, texts, times, actors in g.query(
        "MATCH (t:Ticket) WHERE t.id IN $ids RETURN t.id, t.versions, t.version_times, t.version_actors", {"ids": ids}
    ).result_set:
        texts, times, actors = texts or [], times or [], actors or []
        out[tid] = [{"to": t, "at": from_ms(ms), "actor": actors[i] if i < len(actors) else None} for i, (t, ms) in enumerate(zip(texts, times, strict=False))]
    return out


def next_versions(old: list[dict], body: str, created_at: str, creator: str | None, changed_at: str, editor: str | None) -> tuple[list[dict], bool]:
    """Versions build up from pass to pass: the first pass records the current text, a later one that sees a
    different text adds it as the next version. Returns (versions, whether one was added)."""
    if not old:
        return [{"to": body, "at": created_at, "actor": creator}], False
    if old[-1]["to"] != body:
        return old + [{"to": body, "at": changed_at, "actor": editor}], True
    return old, False


def ticket_event(source: str, tid: str, title: str, body: str, url: str, creator: str | None, assignee: str | None, state: str,
                 labels: list[str], created: str, updated: str, completed: str | None, versions: list[dict]) -> Event:  # fmt: skip
    return Event(
        source=source,
        kind="ticket",
        id=tid,
        author=creator or "unknown",
        ts=created,
        text=f"{title}\n\n{body}",
        url=url,
        extra={
            "title": title,
            "description": body,
            "state": state,
            "labels": labels,
            "assignee": assignee,
            "sprint": None,
            "updated_at": updated,
            "completed_at": completed,
            "versions": versions,
        },
    )


def comment_event(source: str, cid: str, ticket: str, author: str | None, ts: str, text: str, url: str = "") -> Event:
    return Event(source=source, kind="message", id=cid, author=author or "unknown", ts=ts, text=text, url=url, channel=ticket.lower(), extra={"issue": ticket})


def write(g, tickets: list[Event], messages: list[Event], prs: list[Event] | None = None) -> None:
    from graph import writer

    if tickets:
        writer.write_tickets(g, tickets)
    if messages:
        writer.write_messages(g, messages)
        g.query(
            "UNWIND $ps AS p MATCH (m:Message {id: p.m}), (t:Ticket {id: p.t}) MERGE (m)-[:MENTIONS]->(t)",
            {"ps": [{"m": m.id, "t": m.extra["issue"]} for m in messages]},
        )
    if prs:
        writer.write_pull_requests(g, prs)
