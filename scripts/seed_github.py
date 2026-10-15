"""Creates the scenario's 12 PRs on the fictional company's public repo and merges them.

    python -m scripts.seed_github

Use a fresh repo so PR numbers match the answer key (#1..#12). Each PR body ends with a
trailer block (author + scenario dates) because GitHub can't backdate PRs; commit dates
are backdated. Re-running skips PRs whose branch already has a PR.
"""
import base64
import json
import time

import requests

from config import settings
from connectors import scenario
from connectors.github import SCENARIO_PRS, trailer_block

API = "https://api.github.com"


def gh(method, path, **kw):
    r = requests.request(method, f"{API}/repos/{settings.github_repo}{path}", timeout=30, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {settings.github_token}"}, **kw)
    if r.status_code >= 400 and r.status_code != 404:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
    return r


def put_file(path, content, message, branch, author, date):
    existing = gh("GET", f"/contents/{path}", params={"ref": branch})
    body = {"message": message, "branch": branch, "content": base64.b64encode(content.encode()).decode(),
            "author": {"name": author["name"], "email": f"{author['id']}@brightdesk.example", "date": date}}
    if existing.status_code == 200:
        body["sha"] = existing.json()["sha"]
    gh("PUT", f"/contents/{path}", json=body)


def main():
    if not settings.github_token or not settings.github_repo:
        raise SystemExit("Set GITHUB_TOKEN and GITHUB_REPO in .env")
    people = {p["id"]: p for p in scenario.people()}
    prs = json.loads(SCENARIO_PRS.read_text(encoding="utf-8"))
    repo = gh("GET", "").json()
    base = repo["default_branch"]
    if gh("GET", f"/git/ref/heads/{base}").status_code == 404:
        put_file("README.md", "# Brightdesk\n\nHelpdesk for small support teams. (Synthetic demo repo.)\n",
                 "Initial commit", base, people["arjun"], "2026-09-14T04:00:00Z")
    existing = {p["head"]["ref"]: p for p in gh("GET", "/pulls", params={"state": "all", "per_page": 100}).json()}

    for p in prs:
        if p["branch"] in existing:
            print(f"skip #{existing[p['branch']]['number']} {p['title']}")
            continue
        sha = gh("GET", f"/git/ref/heads/{base}").json()["object"]["sha"]
        gh("POST", "/git/refs", json={"ref": f"refs/heads/{p['branch']}", "sha": sha})
        put_file(p["path"], p["content"], p["title"], p["branch"], people[p["author"]], p["created"])
        pr = gh("POST", "/pulls", json={"title": p["title"], "head": p["branch"], "base": base,
                                       "body": p["body"] + "\n" + trailer_block(p["author"], p["created"], p.get("merged"))}).json()
        print(f"opened #{pr['number']} {p['title']}" + ("" if pr["number"] == p["seq"] else f"  (expected #{p['seq']}!)"))
        if p.get("merged"):
            time.sleep(1)
            gh("PUT", f"/pulls/{pr['number']}/merge", json={"merge_method": "squash"})
            gh("DELETE", f"/git/refs/heads/{p['branch']}")


if __name__ == "__main__":
    main()
