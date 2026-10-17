"""A connected team's tickets from Jira Cloud: one project's issues as tickets, with their whole description history.

    sync(g, site, email, token, project, since)   one incremental pass (the team sync runs it every few minutes)

* Issues -> Ticket "<KEY>-<n>" (e.g. ACME-12): summary, description, status (its category "done" -> Done), labels,
  reporter (creator), assignee. Jira keeps every description edit in the issue's changelog, so each version is
  recorded with who wrote it and when, from the start, not only from the first sync on (unlike GitHub's REST API).
* Issue comments -> Messages that MENTION the ticket: a decision in a comment counts like one in chat.
* Reporters, assignees and commenters go through pipeline.identity: a Jira user and the same human's Slack account
  are one Person (by email when Jira shows it, else by full name).
Auth: the Atlassian account's email and an API token (id.atlassian.com > Security > API tokens), read access to the
project. Incremental: JQL `updated >=` the previous pass, with a day of overlap (JQL dates are in the account's time
zone); writes are idempotent, so re-reading an issue changes nothing.
Ticket ids are linked from chat by the usual pattern (2 to 5 letters, a dash, a number): a project key longer than five
letters still syncs, but "#ACMECORP-12" in a message isn't recognised as a link.
"""

import base64
from datetime import UTC, datetime, timedelta

from connectors.github import get_with_retry

FIELDS = "summary,description,status,labels,assignee,reporter,creator,created,updated,resolutiondate,comment"
MAX_ISSUES = 500  # per pass; the next pass continues from the newest update seen


def _site(site: str) -> str:
    site = (site or "").strip().rstrip("/")
    site = site if site.startswith("http") else f"https://{site}"
    if not site.startswith("https://"):
        raise ValueError("the Jira site must be https://<name>.atlassian.net")
    return site


def _headers(email: str, token: str) -> dict:
    basic = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {basic}", "Accept": "application/json"}


def _get(site: str, email: str, token: str, path: str, **params):
    return get_with_retry(f"{_site(site)}{path}", params=params, headers=_headers(email, token)).json()


def iso(ts: str | None) -> str | None:
    """Jira's '2026-10-01T09:00:00.000+0530' -> '2026-10-01T03:30:00Z'."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return ts


def adf_text(node) -> str:
    """Atlassian Document Format (Jira's rich text) -> plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji"):
        return (node.get("attrs") or {}).get("text", "")
    inner = "".join(adf_text(c) for c in node.get("content") or [])
    if kind in ("paragraph", "heading", "blockquote", "codeBlock"):
        return inner.strip() + "\n\n"
    if kind == "listItem":
        return "- " + inner.strip() + "\n"
    return inner


def check_project(site: str, email: str, token: str, project: str) -> dict:
    """Validates the site, credentials and project before they're saved."""
    p = _get(site, email, token, f"/rest/api/3/project/{project.strip().upper()}")
    return {"site": _site(site), "project": p["key"], "name": p.get("name")}


def fetch(site: str, email: str, token: str, project: str, since: str | None = None) -> list[dict]:
    jql = f'project = "{project}"'
    if since:
        local = (datetime.fromisoformat(since.replace("Z", "+00:00")) - timedelta(days=1)).strftime("%Y/%m/%d %H:%M")
        jql += f' AND updated >= "{local}"'
    jql += " ORDER BY updated ASC"
    issues, page = [], None
    while len(issues) < MAX_ISSUES:
        r = _get(site, email, token, "/rest/api/3/search/jql", jql=jql, fields=FIELDS, maxResults=100, **({"nextPageToken": page} if page else {}))
        issues += r.get("issues", [])
        page = r.get("nextPageToken")
        if r.get("isLast", True) or not page:
            break
    return issues


def changelog(site: str, email: str, token: str, key: str) -> list[dict]:
    """Every change to an issue, oldest first."""
    out, start = [], 0
    while True:
        r = _get(site, email, token, f"/rest/api/3/issue/{key}/changelog", startAt=start, maxResults=100)
        out += r.get("values", [])
        start += len(r.get("values", []))
        if r.get("isLast", True) or not r.get("values"):
            return sorted(out, key=lambda h: iso(h.get("created")) or "")


def sync(g, site: str, email: str, token: str, project: str, since: str | None = None, history=None) -> dict:
    """One pass: issues changed since `since`, their description history, their comments; people through identity."""
    from connectors import work

    who = work.People(g, "jira")

    def person(u: dict | None) -> str | None:
        if not u or not u.get("accountId"):
            return None
        return who(u["accountId"], u.get("displayName"), u.get("displayName"), u.get("emailAddress"))

    issues = fetch(site, email, token, project, since)
    tickets, messages, new_versions = [], [], 0
    old = work.stored_versions(g, [i["key"] for i in issues])
    for i in issues:
        f, key = i["fields"], i["key"]
        creator, assignee = person(f.get("reporter") or f.get("creator")), person(f.get("assignee"))
        created, updated = iso(f["created"]), iso(f["updated"])
        body = adf_text(f.get("description")).strip()
        edits = [
            (iso(h["created"]), person(h.get("author")), it.get("fromString") or "", it.get("toString") or "")
            for h in (history or changelog)(site, email, token, key)
            for it in h.get("items", [])
            if it.get("field") == "description"
        ]
        if edits:  # the whole history: the text it was created with, then every edit, each by its author
            versions = ([{"to": edits[0][2], "at": created, "actor": creator}] if edits[0][2].strip() else []) + [
                {"to": to, "at": at, "actor": by or creator} for at, by, _, to in edits if to.strip()
            ]
            new_versions += max(0, len(versions) - len(old.get(key, [])))
        else:
            versions, added = work.next_versions(old.get(key, []), body, created, creator, updated, assignee or creator)
            new_versions += added
        status = f.get("status") or {}
        state = "Done" if (status.get("statusCategory") or {}).get("key") == "done" else status.get("name") or "Open"
        url = f"{_site(site)}/browse/{key}"
        tickets.append(
            work.ticket_event(
                "jira",
                key,
                f.get("summary") or key,
                body,
                url,
                creator,
                assignee,
                state,
                f.get("labels") or [],
                created,
                updated,
                iso(f.get("resolutiondate")),
                versions,
            )
        )
        for c in ((f.get("comment") or {}).get("comments")) or []:
            text = adf_text(c.get("body")).strip()
            if text:
                messages.append(
                    work.comment_event("jira", f"jirac:{c['id']}", key, person(c.get("author")), iso(c["created"]), text, f"{url}?focusedCommentId={c['id']}")
                )
    work.write(g, tickets, messages)
    stamps = [iso(i["fields"]["updated"]) for i in issues]
    return {
        "tickets": len(tickets),
        "new_versions": new_versions,
        "comments": len(messages),
        "prs": 0,
        "people": who.count,
        "until": max(stamps) if stamps else since,
    }
