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


def _event(number: int, title: str, body: str, url: str, state: str, fallback_author: str, created: str, merged: str | None) -> Event:
    text, tr = parse_body(body)
    return Event(
        source="github",
        kind="pull_request",
        id=f"PR-{number}",
        author=tr.get("Authored-by", fallback_author),
        ts=tr.get("Scenario-created", created),
        text=f"{title}\n\n{text}",
        url=url,
        extra={
            "number": number,
            "title": title,
            "body": text,
            "state": state,
            "merged_at": tr.get("Scenario-merged", merged),
        },
    )


def get_with_retry(url: str, *, params=None, headers=None, attempts: int = 5, sleep=None):
    """GET with backoff on GitHub's rate limits (403/429 with Retry-After or X-RateLimit-Reset) and 5xx."""
    import time

    sleep = sleep or time.sleep
    for i in range(attempts):
        r = requests.get(url, params=params, headers=headers, timeout=20)
        limited = r.status_code in (403, 429) and (r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Remaining") == "0")
        if not (limited or r.status_code >= 500) or i == attempts - 1:
            r.raise_for_status()
            return r
        if r.headers.get("Retry-After"):
            wait = float(r.headers["Retry-After"])
        elif r.headers.get("X-RateLimit-Reset"):
            wait = max(0.0, float(r.headers["X-RateLimit-Reset"]) - time.time()) + 1
        else:
            wait = 2**i
        sleep(min(wait, 60.0))
    raise RuntimeError("unreachable")


def pull_requests_from_api(repo: str | None = None) -> list[Event]:
    repo = repo or settings.github_repo
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    events, page = [], 1
    while True:
        r = get_with_retry(f"https://api.github.com/repos/{repo}/pulls", params={"state": "all", "per_page": 100, "page": page}, headers=headers)
        batch = r.json()
        for pr in batch:
            events.append(
                _event(
                    pr["number"],
                    pr["title"],
                    pr.get("body") or "",
                    pr["html_url"],
                    "merged" if pr.get("merged_at") else pr["state"],
                    pr["user"]["login"],
                    pr["created_at"],
                    pr.get("merged_at"),
                )
            )
        if len(batch) < 100:
            return events
        page += 1


def pull_requests_from_scenario() -> list[Event]:
    """Offline equivalent of the API: same events the seeded repo would return."""
    prs = json.loads(SCENARIO_PRS.read_text(encoding="utf-8"))
    return [
        _event(
            p["seq"],
            p["title"],
            p["body"] + trailer_block(p["author"], p["created"], p["merged"]),
            f"scenario://github/pull/{p['seq']}",
            "merged" if p.get("merged") else "open",
            p["author"],
            p["created"],
            p.get("merged"),
        )
        for p in prs
    ]
