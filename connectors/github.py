"""GitHub connector: pull requests from the fictional company's public repo.

GitHub can't backdate PRs, so seeded PRs end with a trailer block:

    ---
    Authored-by: sofia
    Scenario-created: 2026-09-24T10:00:00Z
    Scenario-merged: 2026-09-25T05:44:00Z

The connector prefers those values when present and falls back to the real API
fields, so PRs opened live during the demo work unchanged.
"""
import json
import re
from pathlib import Path

import requests

from config import settings
from pipeline.events import Event

SCENARIO_PRS = Path(__file__).resolve().parent.parent / "data" / "scenario" / "pull_requests.json"
TRAILER = re.compile(r"^(Authored-by|Scenario-created|Scenario-merged):\s*(\S+)\s*$", re.M)


def trailer_block(author: str, created: str, merged: str | None) -> str:
    lines = ["", "---", f"Authored-by: {author}", f"Scenario-created: {created}"]
    if merged:
        lines.append(f"Scenario-merged: {merged}")
    return "\n".join(lines)


def parse_body(body: str) -> tuple[str, dict]:
    """Split a PR body into (human text, trailer fields)."""
    body = body or ""
    fields = dict(TRAILER.findall(body))
    text = body.split("\n---\n")[0].strip() if fields else body.strip()
    return text, fields


def _event(number: int, title: str, body: str, url: str, state: str,
           fallback_author: str, created: str, merged: str | None) -> Event:
    text, tr = parse_body(body)
    return Event(
        source="github", kind="pull_request", id=f"PR-{number}",
        author=tr.get("Authored-by", fallback_author),
        ts=tr.get("Scenario-created", created),
        text=f"{title}\n\n{text}", url=url,
        extra={
            "number": number, "title": title, "body": text, "state": state,
            "merged_at": tr.get("Scenario-merged", merged),
        },
    )


def pull_requests_from_api(repo: str | None = None) -> list[Event]:
    repo = repo or settings.github_repo
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    events, page = [], 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{repo}/pulls",
                         params={"state": "all", "per_page": 100, "page": page},
                         headers=headers, timeout=20)
        r.raise_for_status()
        batch = r.json()
        for pr in batch:
            events.append(_event(
                pr["number"], pr["title"], pr.get("body") or "", pr["html_url"],
                "merged" if pr.get("merged_at") else pr["state"],
                pr["user"]["login"], pr["created_at"], pr.get("merged_at"),
            ))
        if len(batch) < 100:
            return events
        page += 1


def pull_requests_from_scenario() -> list[Event]:
    """Offline equivalent of the API: same events the seeded repo would return."""
    prs = json.loads(SCENARIO_PRS.read_text(encoding="utf-8"))
    return [
        _event(p["seq"], p["title"], p["body"] + trailer_block(p["author"], p["created"], p["merged"]),
               f"scenario://github/pull/{p['seq']}", "merged" if p.get("merged") else "open",
               p["author"], p["created"], p.get("merged"))
        for p in prs
    ]
