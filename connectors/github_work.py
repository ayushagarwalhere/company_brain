"""A connected team's work from GitHub: issues as tickets, issue comments as discussion, pull requests as PRs.

    sync(g, repo, token, since)   one incremental pass (the team sync calls it every few minutes)

* Issues -> Ticket "GH-<n>": title, body, state, labels, creator, first assignee. "#12" in any text becomes "GH-12",
  so the ticket-id links work the same as for "BD-101".
* Ticket versions build up over time: the first sync records the current body (as of the issue's creation; GitHub's
  REST API doesn't give earlier edits), and every later sync that sees a different body adds a new version, stamped
  with the issue's update time and its editor's identity unknown (the ticket's owner is assumed). Polling every few
  minutes keeps those times close to the real edit.
* Issue comments -> Message in channel "issue-<n>", MENTIONS its ticket: decisions made in a comment count like
  decisions made in chat. Pull requests (the issues API includes them) -> PullRequest "PR-<n>", merged or not.
* Every login goes through pipeline.identity, so a GitHub author and the same human's Slack account are one Person,
  and "only the ticket's creator or assignee can change it" holds across both.
Incremental: the issues and comments endpoints take `since`; a sync asks for what changed after the previous one.
"""

import re

from connectors.github import get_with_retry
from pipeline.events import Event

API = "https://api.github.com"
HASH_REF = re.compile(r"(?<![\w/&])#(\d{1,6})\b")
MAX_PAGES = 20  # 2000 issues and 2000 comments per pass; the next pass continues from where this one stopped


def gh_ids(text: str | None) -> str:
    """'#123' -> 'GH-123', so the ticket-id regex links it."""
    return HASH_REF.sub(lambda m: f"GH-{m.group(1)}", text or "")


def _get(path: str, token: str | None, **params):
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    return get_with_retry(f"{API}{path}", params=params, headers=headers).json()


def _paged(path: str, token: str | None, **params) -> list[dict]:
    out = []
    for page in range(1, MAX_PAGES + 1):
        batch = _get(path, token, per_page=100, page=page, **params)
        out += batch
        if len(batch) < 100:
            break
    return out


def check_repo(repo: str, token: str | None) -> dict:
    """Validates a repo before it's saved: exists and readable with this token."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        raise ValueError("repo must look like owner/name")
    r = _get(f"/repos/{repo}", token)
    return {"repo": r["full_name"], "private": r["private"], "open_issues": r.get("open_issues_count")}


def fetch(repo: str, token: str | None, since: str | None = None) -> dict:
    params = {"state": "all", "sort": "updated", "direction": "asc", **({"since": since} if since else {})}
    items = _paged(f"/repos/{repo}/issues", token, **params)
    comments = _paged(f"/repos/{repo}/issues/comments", token, sort="updated", direction="asc", **({"since": since} if since else {}))
    return {"items": items, "comments": comments}


def user_details(login: str, token: str | None) -> dict:
    """A GitHub user's public name and email, used to match them to their Slack or Discord account."""
    try:
        u = _get(f"/users/{login}", token)
        return {"name": u.get("name"), "email": u.get("email")}
    except Exception:  # noqa: BLE001 - matching falls back to the login
        return {}


def sync(g, repo: str, token: str | None, since: str | None = None, people=None) -> dict:
    """One pass: fetch what changed since `since`, map every login to a person, write tickets, comments and PRs.
    Returns counts and the newest update time seen (the next pass's `since`)."""
    from connectors import work

    snap = fetch(repo, token, since)
    who = work.People(g, "github")

    def person(user: dict | None) -> str | None:
        """A GitHub user -> their Person. Bots (dependabot, Copilot, *[bot]) get a bot id, not a person in Who's who."""
        login = (user or {}).get("login")
        if not login:
            return None
        if user.get("type") == "Bot" or login.endswith("[bot]"):
            return f"bot:{login.removesuffix('[bot]')}"
        return who(login, login, details=lambda: (people or user_details)(login, token))

    issues = [i for i in snap["items"] if "pull_request" not in i]
    prs = [i for i in snap["items"] if "pull_request" in i]
    old = work.stored_versions(g, [f"GH-{i['number']}" for i in issues])
    tickets, new_versions = [], 0
    for i in issues:
        tid, body = f"GH-{i['number']}", gh_ids(i.get("body"))
        creator = person(i["user"])
        assignee = person((i.get("assignees") or [{}])[0]) if i.get("assignees") else None
        versions, added = work.next_versions(old.get(tid, []), body, i["created_at"], creator, i["updated_at"], assignee or creator)
        new_versions += added
        labels = [lb["name"] for lb in i.get("labels") or []]
        state = "Done" if i["state"] == "closed" else "Open"
        tickets.append(
            work.ticket_event(
                "github", tid, i["title"], body, i["html_url"], creator, assignee, state, labels, i["created_at"], i["updated_at"], i.get("closed_at"), versions
            )
        )
    numbers = {i["number"] for i in issues} | {int(r[0].split("-")[1]) for r in g.query("MATCH (t:Ticket) WHERE t.id STARTS WITH 'GH-' RETURN t.id").result_set}
    messages = []
    for c in snap["comments"]:
        n = int(c["issue_url"].rsplit("/", 1)[1])
        if n not in numbers or (c.get("user") or {}).get("type") == "Bot":
            continue  # a PR's comment, or a bot's
        messages.append(work.comment_event("github", f"ghc:{c['id']}", f"GH-{n}", person(c["user"]), c["created_at"], gh_ids(c.get("body")), c["html_url"]))
    pr_events = [
        Event(
            source="github",
            kind="pull_request",
            id=f"PR-{p['number']}",
            author=person(p["user"]) or "unknown",
            ts=p["created_at"],
            text=f"{p['title']}\n\n{gh_ids(p.get('body'))}",
            url=p["html_url"],
            extra={
                "number": p["number"],
                "title": p["title"],
                "body": gh_ids(p.get("body")),
                "state": "merged" if (p.get("pull_request") or {}).get("merged_at") else p["state"],
                "merged_at": (p.get("pull_request") or {}).get("merged_at"),
            },
        )
        for p in prs
    ]
    work.write(g, tickets, messages, pr_events)
    stamps = [x["updated_at"] for x in snap["items"]] + [c["updated_at"] for c in snap["comments"]]
    return {
        "tickets": len(tickets),
        "new_versions": new_versions,
        "comments": len(messages),
        "prs": len(pr_events),
        "people": who.count,
        "until": max(stamps) if stamps else since,
    }
