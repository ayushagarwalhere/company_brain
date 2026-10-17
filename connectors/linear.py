"""A connected team's tickets from Linear: one team's issues as tickets, their comments as discussion.

    sync(g, token, team, since)   one incremental pass (the team sync runs it every few minutes)

* Issues -> Ticket "<TEAM>-<n>" (e.g. ENG-12): title, description, state (completed -> Done, canceled -> Canceled),
  labels, creator, assignee. Linear's history says when the description was last edited and by whom (not the old
  text), so the first pass dates the current text correctly, and every later pass that sees a new text adds it as the
  next version.
* Comments -> Messages that MENTION the ticket: a decision in a comment counts like one in chat.
* Creators, assignees and commenters go through pipeline.identity: a Linear user and the same human's Slack account are
  one Person (Linear gives the email to the workspace's API key).
Auth: a personal API key (Linear > Settings > Security & access > API keys), read access. GraphQL, filtered on
`updatedAt > ` the previous pass.
"""

import requests

API = "https://api.linear.app/graphql"
EPOCH = "1970-01-01T00:00:00.000Z"
MAX_PAGES = 20  # 50 issues a page

USER = "id name displayName email"
ISSUES = """query Issues($team: String!, $since: DateTimeOrDuration!, $after: String) {
  issues(first: 50, after: $after, orderBy: updatedAt, filter: {team: {key: {eq: $team}}, updatedAt: {gt: $since}}) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id identifier title description url createdAt updatedAt completedAt canceledAt
      state { name type } labels { nodes { name } }
      creator { USER } assignee { USER }
      comments(first: 50) { nodes { id body createdAt url user { USER } } }
      HISTORY
    }
  }
}"""
HISTORY = "history(first: 50) { nodes { createdAt updatedDescription actor { USER } } }"


def graphql(token: str, query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        API, json={"query": query, "variables": variables or {}}, headers={"Authorization": token.strip(), "Content-Type": "application/json"}, timeout=30
    )
    data = r.json() if r.content else {}
    if r.status_code >= 400 or data.get("errors"):
        raise RuntimeError(f"Linear: {(data.get('errors') or [{}])[0].get('message') or r.status_code}")
    return data["data"]


def check_team(token: str, team: str) -> dict:
    """Validates the key and the team before they're saved."""
    nodes = graphql(token, "query($k: String!) { teams(filter: {key: {eq: $k}}) { nodes { id key name } } }", {"k": team.strip().upper()})["teams"]["nodes"]
    if not nodes:
        raise ValueError(f"no Linear team with key {team.upper()} for this API key")
    return {"team": nodes[0]["key"], "name": nodes[0]["name"]}


def fetch(token: str, team: str, since: str | None = None, query=None) -> list[dict]:
    q = query or graphql
    issues, after = [], None
    with_history = True
    for _ in range(MAX_PAGES):
        text = ISSUES.replace("HISTORY", HISTORY if with_history else "").replace("USER", USER)
        try:
            page = q(token, text, {"team": team, "since": since or EPOCH, "after": after})["issues"]
        except RuntimeError as e:
            if with_history and "history" in str(e).lower():  # an API without issue history: carry on without it
                with_history = False
                continue
            raise
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues


def _iso(ts: str | None) -> str | None:
    return ts[:19] + "Z" if ts else None


def sync(g, token: str, team: str, since: str | None = None, query=None) -> dict:
    from connectors import work

    who = work.People(g, "linear")

    def person(u: dict | None) -> str | None:
        return who(u["id"], u.get("displayName"), u.get("name"), u.get("email")) if u and u.get("id") else None

    issues = fetch(token, team, since, query)
    old = work.stored_versions(g, [i["identifier"] for i in issues])
    tickets, messages, new_versions = [], [], 0
    for i in issues:
        key, body = i["identifier"], (i.get("description") or "").strip()
        creator, assignee = person(i.get("creator")), person(i.get("assignee"))
        edits = [h for h in ((i.get("history") or {}).get("nodes") or []) if h.get("updatedDescription")]
        last = max(edits, key=lambda h: h["createdAt"]) if edits else None
        first_at = _iso(last["createdAt"]) if last else _iso(i["createdAt"])  # when the current text was written
        first_by = person(last.get("actor")) if last and last.get("actor") else creator
        if not old.get(key):
            versions, added = [{"to": body, "at": first_at, "actor": first_by}], False
        else:
            # a new text is dated by its history entry only if that entry is newer than the version already stored (the
            # history Linear returns may stop short of the latest edit); otherwise by the issue's update time
            fresh = bool(first_at and first_at > (old[key][-1]["at"] or ""))
            changed_at, editor = (first_at, first_by) if fresh else (_iso(i["updatedAt"]), assignee or creator)
            versions, added = work.next_versions(old[key], body, first_at, first_by, changed_at, editor)
        new_versions += added
        st = i.get("state") or {}
        state = {"completed": "Done", "canceled": "Canceled"}.get(st.get("type"), st.get("name") or "Open")
        labels = [lb["name"] for lb in (i.get("labels") or {}).get("nodes") or []]
        tickets.append(
            work.ticket_event(
                "linear",
                key,
                i["title"],
                body,
                i["url"],
                creator,
                assignee,
                state,
                labels,
                _iso(i["createdAt"]),
                _iso(i["updatedAt"]),
                _iso(i.get("completedAt")),
                versions,
            )
        )
        for c in (i.get("comments") or {}).get("nodes") or []:
            if (c.get("body") or "").strip():
                messages.append(
                    work.comment_event(
                        "linear", f"linc:{c['id']}", key, person(c.get("user")), _iso(c["createdAt"]), c["body"].strip(), c.get("url") or i["url"]
                    )
                )
    work.write(g, tickets, messages)
    stamps = [i["updatedAt"] for i in issues]
    return {
        "tickets": len(tickets),
        "new_versions": new_versions,
        "comments": len(messages),
        "prs": 0,
        "people": who.count,
        "until": max(stamps) if stamps else since,
    }
