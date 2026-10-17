"""Try it on your own repo: a public GitHub repo's most recently updated issues and PRs, and their comments, through
the same pipeline as everything else (rules extractor, no LLM: fast and free), into a graph of its own. Then what the
graph shows about it:

    people        who did what: issues opened, PRs authored and merged, comments, assignments
    areas         who knows what, per label: the people behind each area's issues and the PRs that close them
    chains        issue <- PR links ("fixes #12"), with who opened the issue and who wrote the PR
    decisions     changes to an issue's requirement stated in its comments (rules: candidates, see the note)
    no_pr         open issues no PR in the window references
    drift         decisions in comments the issue body never caught up with (rules: candidates)
    graph         the chains and decisions as a layered graph

Mapping (benchmark/real_data.py's adapter, unchanged): issue -> Ticket GH-<n>, issue comment -> Message that MENTIONS
it, PR -> PullRequest ("#12" -> GH-12 so hard links resolve). Comments on PRs aren't chat about requirements; their
authors get a REVIEWED edge to the PR, for "who knows". Bot accounts are left out.

Window: the TRY_ISSUES most recently updated issues (default 150) and TRY_PRS PRs (default 100), the issues those PRs
reference (up to TRY_REF_ISSUES more, default 25, only with a server token: without one GitHub allows 60 calls an hour),
and TRY_COMMENT_PAGES x 100 of the most recent comments (default 4).
Limits, so it stays quick and cheap:
a result is reused for TRY_TTL_HOURS (default 12), at most TRY_MAX_REPOS graphs are kept (oldest dropped), two builds at
a time. Private repos are refused even when the server's token could read them.
"""

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.getenv("TRY_CACHE_DIR", str(ROOT / "data" / "try")))
ISSUES = int(os.getenv("TRY_ISSUES", "150"))
PRS = min(100, int(os.getenv("TRY_PRS", "100")))
REF_ISSUES = int(os.getenv("TRY_REF_ISSUES", "25"))
COMMENT_PAGES = int(os.getenv("TRY_COMMENT_PAGES", "4"))
TTL_H = float(os.getenv("TRY_TTL_HOURS", "12"))
MAX_REPOS = int(os.getenv("TRY_MAX_REPOS", "40"))
PREWARM = [r.strip() for r in os.getenv("TRY_PREWARM", "FalkorDB/FalkorDB").split(",") if r.strip()]

REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
HASH_REF = re.compile(r"(?<![\w/&])#(\d{1,6})\b")
URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)", re.I)

# the honest part, shown on the page with every result
NOTE = (
    "Drift on real text is the weakest part. The rules extractor only catches explicitly worded changes "
    "('decision:', 'let's switch', 'we'll support', 'instead of'), and on 60 hand-labelled real comments its precision "
    "was 0.17 (1 of 6 flagged) and its recall 0.14 (1 of 7). So treat decisions and drift here as candidates to read, "
    "and an empty list as 'nothing explicitly worded', not 'everything is current'. People, areas and issue-PR chains "
    "come from GitHub's own links and are reliable within the window read."
)


class TryError(Exception):
    """A message for the person who pasted the repo."""


def parse(text: str) -> str:
    """'owner/name', or a github.com URL to it -> 'owner/name'."""
    t = (text or "").strip().rstrip("/")
    m = URL_RE.match(t)
    if m:
        t = f"{m.group(1)}/{m.group(2)}"
    t = re.sub(r"\.git$", "", t)
    if not REPO_RE.match(t):
        raise TryError("Paste a public GitHub repo as owner/name, e.g. FalkorDB/FalkorDB, or its github.com URL.")
    return t


def org_for(repo: str) -> str:
    """The repo's own org (and graph): readable when it fits, hashed when it doesn't."""
    slug = re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
    org = f"gh-{slug}"
    return org if len(org) <= 40 else f"gh-{slug[:26].strip('-')}-{sha1(repo.lower().encode()).hexdigest()[:8]}"


def is_repo_org(org: str | None) -> bool:
    return bool(org) and str(org).startswith("gh-")


# ---------------------------------------------------------------- fetch


def _token() -> str:
    from config import settings

    return (settings.github_token or "").strip()


def _gh(path: str, **params):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = _token()
    for auth in [True, False] if token else [False]:
        h = {**headers, **({"Authorization": f"Bearer {token}"} if auth else {})}
        r = requests.get(f"https://api.github.com{path}", params=params, headers=h, timeout=20)
        if r.status_code == 401 and auth:
            continue  # a bad server token mustn't block public reads
        if r.status_code == 404:
            raise TryError("No public GitHub repo by that name.")
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            wait = max(1, int(r.headers.get("X-RateLimit-Reset", "0")) - int(time.time())) // 60 + 1
            raise TryError(f"GitHub's rate limit for this server is used up; try again in about {wait} minutes.")
        r.raise_for_status()
        return r.json()
    raise TryError("GitHub refused the request.")


def _bot(user: dict | None) -> bool:
    return not user or user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")


def fetch(repo: str, step=lambda s: None) -> dict:
    """The snapshot benchmark/real_data.py's adapter reads, from the live API, plus PR comment authors."""
    step("Checking the repo")
    meta = _gh(f"/repos/{repo}")
    if meta.get("private") or meta.get("visibility", "public") != "public":
        raise TryError("That repo is private. Only public repos can be tried here.")
    repo = meta["full_name"]
    step(f"Reading the {ISSUES} most recently updated issues")
    raw: list[dict] = []
    for page in range(1, (ISSUES + 99) // 100 + 2):  # /issues pages include PRs, which are skipped here
        batch = _gh(f"/repos/{repo}/issues", state="all", sort="updated", direction="desc", per_page=100, page=page)
        raw += [i for i in batch if "pull_request" not in i and not _bot(i.get("user"))]
        if len(raw) >= ISSUES or len(batch) < 100:
            break
    raw = raw[:ISSUES]
    step(f"Reading the {PRS} most recently updated pull requests")
    pulls = [
        {**pr, "pull_request": {"merged_at": pr.get("merged_at")}}
        for pr in _gh(f"/repos/{repo}/pulls", state="all", sort="updated", direction="desc", per_page=PRS)
        if not _bot(pr.get("user"))
    ]
    have = {i["number"] for i in raw} | {pr["number"] for pr in pulls}
    refs = sorted({int(n) for pr in pulls for n in HASH_REF.findall(f"{pr.get('title') or ''} {pr.get('body') or ''}")} - have, reverse=True)
    if refs and _token():
        step(f"Reading {min(len(refs), REF_ISSUES)} older issues those PRs reference")

        def one(n: int) -> dict | None:
            try:
                return _gh(f"/repos/{repo}/issues/{n}")
            except (TryError, requests.RequestException):
                return None

        with ThreadPoolExecutor(max_workers=6) as pool:
            older = [i for i in pool.map(one, refs[:REF_ISSUES]) if i and "pull_request" not in i and not _bot(i.get("user"))]
        raw += older
    else:
        older = []
    items = raw + pulls
    if not items:
        raise TryError("That repo has no issues or pull requests to read.")
    step("Reading their comments")
    since = min(i["updated_at"] for i in items)
    comments: list[dict] = []
    for page in range(1, COMMENT_PAGES + 1):
        batch = _gh(f"/repos/{repo}/issues/comments", since=since, sort="updated", direction="desc", per_page=100, page=page)
        comments += [c for c in batch if not _bot(c.get("user"))]
        if len(batch) < 100:
            break
    issues = []
    for i in items:
        pr = i.get("pull_request")
        merged = (pr or {}).get("merged_at")
        issues.append(
            {
                "number": i["number"],
                "title": i["title"],
                "body": i.get("body") or "",
                "state": i["state"],
                "labels": [lb["name"] for lb in i.get("labels") or [] if isinstance(lb, dict)],
                "assignees": [a["login"] for a in i.get("assignees") or []],
                "user": i["user"]["login"],
                "created_at": i["created_at"],
                "closed_at": i.get("closed_at"),
                "html_url": i["html_url"],
                "merged_at": merged,
                "is_pr": pr is not None,
                "comments": i.get("comments", 0),
            }
        )
    return {
        "repo": repo,
        "description": meta.get("description"),
        "stars": meta.get("stargazers_count"),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "live",
        "older_issues": len(older),
        "issues": issues,
        "comments": [
            {
                "id": c["id"],
                "issue_url": c["issue_url"],
                "user": c["user"]["login"],
                "body": c.get("body") or "",
                "created_at": c["created_at"],
                "html_url": c["html_url"],
            }
            for c in comments
        ],
    }


def from_snapshot(repo: str) -> dict | None:
    """The bundled snapshot (data/real/), for pre-warming when GitHub can't be reached."""
    from benchmark import real_data

    if not real_data.snapshot_path(repo).exists():
        return None
    snap = real_data.load_snapshot(repo)
    human = [i for i in snap["issues"] if not str(i["user"]).endswith("[bot]")]
    snap["issues"] = [i for i in human if not i["is_pr"]][:ISSUES] + [i for i in human if i["is_pr"]][:PRS]
    snap["comments"] = [c for c in snap["comments"] if not str(c["user"]).endswith("[bot]")][: COMMENT_PAGES * 100]
    return {**snap, "source": f"snapshot of {snap['fetched_at'][:10]}", "description": None, "stars": None}


# ---------------------------------------------------------------- build


def build(snap: dict, org: str) -> dict:
    """The repo's graph, from scratch: the real-data adapter's events, then the full pipeline (rules)."""
    from benchmark.real_data import to_events
    from graph import writer
    from graph.db import get_db, get_graph, org_graph_name
    from pipeline.resolve import resolve

    name = org_graph_name(org)
    if name in get_db().list_graphs():
        get_graph(name).delete()
    g = get_graph(name)
    writer.apply_schema(g)
    tickets, messages, prs = to_events(snap)
    writer.write_tickets(g, tickets)
    writer.write_messages(g, messages)
    g.query(
        "UNWIND $ps AS p MATCH (m:Message {id: p.m}), (t:Ticket {id: p.t}) MERGE (m)-[:MENTIONS]->(t)",
        {"ps": [{"m": m.id, "t": m.extra["issue"]} for m in messages]},
    )
    writer.write_pull_requests(g, prs)
    resolve(g, "heuristic", log=lambda *_: None, one_feature_per_ticket=True)
    pr_numbers = {i["number"] for i in snap["issues"] if i["is_pr"]}
    reviews = {(c["user"], int(c["issue_url"].rsplit("/", 1)[1])) for c in snap["comments"]}
    g.query(
        """UNWIND $rs AS r MATCH (pr:PullRequest {number: r.n}) MERGE (p:Person {id: r.p})
           SET p.name = coalesce(p.name, r.p) MERGE (p)-[:REVIEWED]->(pr)""",
        {"rs": [{"p": u, "n": n} for u, n in reviews if n in pr_numbers]},
    )
    g.query("MATCH (p:Person) WHERE p.name IS NULL SET p.name = p.id")
    return summary(g, snap)


def _known_labels() -> dict[str, dict]:
    """Comments already hand-checked for the real-data benchmark (benchmark/real_data_labels.json, made by the AI
    assistant): a flag the page shows again carries that verdict next to it, so a known false positive says so."""
    try:
        data = json.loads((ROOT / "benchmark" / "real_data_labels.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {x["url"]: {"verdict": x["verdict"], "pattern": x.get("pattern"), "note": x.get("note")} for x in data.get("labels", []) if x.get("url")}


def _ticket_n(tid: str) -> int:
    return int(tid.split("-")[1])


def summary(g, snap: dict) -> dict:
    """What the graph shows about the repo (every list is a graph query, not a GitHub API call)."""
    from graph import queries as Q

    repo = snap["repo"]
    gh = f"https://github.com/{repo}"
    rows = Q.rows(
        g,
        """MATCH (t:Ticket)
           OPTIONAL MATCH (a:Person)-[:AUTHORED]->(t)
           OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(s:Person)
           OPTIONAL MATCH (c:Person)-[:POSTED]->(:Message)-[:MENTIONS]->(t)
           OPTIONAL MATCH (b:Person)-[:AUTHORED]->(pr:PullRequest)-[:REFERENCES]->(t)
           RETURN t.id AS id, t.title AS title, t.state AS state, t.labels AS labels, t.url AS url, a.id AS author, s.id AS assignee,
                  collect(DISTINCT c.id) AS commenters, collect(DISTINCT b.id) AS pr_authors, count(DISTINCT pr) AS prs""",
    )
    prs = Q.rows(
        g,
        """MATCH (a:Person)-[:AUTHORED]->(pr:PullRequest) OPTIONAL MATCH (r:Person)-[:REVIEWED]->(pr)
           RETURN pr.number AS number, pr.state AS state, a.id AS author, collect(DISTINCT r.id) AS reviewers""",
    )

    # people: what each one did in the window
    people: dict[str, dict] = {}

    def p(pid: str) -> dict:
        return people.setdefault(
            pid,
            {"person": pid, "url": f"https://github.com/{pid}", "issues": 0, "prs": 0, "merged": 0, "comments": 0, "assigned": 0, "reviews": 0, "areas": {}},
        )

    for t in rows:
        if t["author"]:
            p(t["author"])["issues"] += 1
        if t["assignee"]:
            p(t["assignee"])["assigned"] += 1
        for c in t["commenters"]:
            p(c)["comments"] += 1
    for r in prs:
        p(r["author"])["prs"] += 1
        p(r["author"])["merged"] += r["state"] == "merged"
        for rv in r["reviewers"]:
            if rv != r["author"]:
                p(rv)["reviews"] += 1

    # areas: per label, who is behind its issues (opened 1, commented 1, assigned 2, wrote a PR for it 3)
    areas: dict[str, dict] = {}
    for t in rows:
        for lab in t["labels"] or []:
            a = areas.setdefault(lab, {"label": lab, "issues": 0, "open": 0, "with_pr": 0, "scores": {}})
            a["issues"] += 1
            a["open"] += t["state"] == "open"
            a["with_pr"] += t["prs"] > 0
            for pid, w in [(t["author"], 1), (t["assignee"], 2), *((c, 1) for c in t["commenters"]), *((b, 3) for b in t["pr_authors"])]:
                if pid:
                    a["scores"][pid] = a["scores"].get(pid, 0) + w
                    p(pid)["areas"][lab] = p(pid)["areas"].get(lab, 0) + w
    area_list = []
    for a in sorted(areas.values(), key=lambda a: (-a["issues"], a["label"]))[:10]:
        top = sorted(a.pop("scores").items(), key=lambda kv: (-kv[1], kv[0]))[:4]
        area_list.append({**a, "people": [{"person": k, "score": v} for k, v in top], "url": f"{gh}/issues?q=label%3A%22{requests.utils.quote(a['label'])}%22"})
    for v in people.values():
        v["score"] = v["issues"] + v["comments"] + 2 * v["assigned"] + 3 * v["prs"] + v["merged"] + v["reviews"]
        v["areas"] = [k for k, _ in sorted(v["areas"].items(), key=lambda kv: -kv[1])[:3]]
    people_list = sorted(people.values(), key=lambda v: (-v["score"], v["person"]))[:12]

    chains = Q.rows(
        g,
        """MATCH (b:Person)-[:AUTHORED]->(pr:PullRequest)-[ref:REFERENCES]->(t:Ticket)
           OPTIONAL MATCH (a:Person)-[:AUTHORED]->(t)
           RETURN t.id AS issue, t.title AS issue_title, t.url AS issue_url, t.state AS issue_state, a.id AS opened_by,
                  pr.number AS pr, pr.title AS pr_title, pr.url AS pr_url, pr.state AS pr_state, b.id AS pr_by,
                  coalesce(ref.how, 'hard') AS how, coalesce(pr.merged_ms, pr.created_ms) AS at
           ORDER BY at DESC""",
    )
    decisions = Q.rows(
        g,
        """MATCH (p:Person)-[:POSTED]->(m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)
           OPTIONAL MATCH (pr:PullRequest)-[:IMPLEMENTS]->(r)
           RETURN p.id AS by, m.text AS comment, m.url AS url, m.ts AS at, r.id AS requirement, r.text AS requirement_text,
                  t.id AS issue, t.title AS issue_title, t.url AS issue_url, collect(DISTINCT pr.number) AS implemented_by
           ORDER BY at DESC""",
    )
    drift = Q.drift(g)
    drifted = {d["requirement"] for d in drift}
    known = _known_labels()
    open_no_pr = [t for t in rows if t["state"] == "open" and t["prs"] == 0]
    comment_count = {i["number"]: i.get("comments", 0) for i in snap["issues"]}
    open_no_pr.sort(key=lambda t: (-comment_count.get(_ticket_n(t["id"]), 0), -_ticket_n(t["id"])))
    n_issues = sum(1 for i in snap["issues"] if not i["is_pr"])
    n_prs = sum(1 for i in snap["issues"] if i["is_pr"])
    return {
        "repo": repo,
        "url": gh,
        "description": snap.get("description"),
        "stars": snap.get("stars"),
        "fetched_at": snap["fetched_at"],
        "source": snap.get("source", "live"),
        "window": {
            "issues": n_issues,
            "older_issues": snap.get("older_issues", 0),
            "prs": n_prs,
            "comments": len(snap["comments"]),
            "cap_issues": ISSUES,
            "cap_prs": PRS,
        },
        "counts": {
            "people": len(people),
            "issues": n_issues,
            "open_issues": sum(1 for t in rows if t["state"] == "open"),
            "prs": n_prs,
            "merged": sum(1 for r in prs if r["state"] == "merged"),
            "chains": len(chains),
            "decisions": len(decisions),
            "drift": len(drift),
            "open_no_pr": len(open_no_pr),
        },
        "people": people_list,
        "areas": area_list,
        "chains": chains[:20],
        "decisions": [{**d, "comment": plain(d["comment"]), "drift": d["requirement"] in drifted, "label": known.get(d["url"])} for d in decisions[:15]],
        "no_pr": [
            {
                "issue": t["id"],
                "title": t["title"],
                "url": t["url"],
                "labels": t["labels"] or [],
                "opened_by": t["author"],
                "assignee": t["assignee"],
                "comments": comment_count.get(_ticket_n(t["id"]), 0),
            }
            for t in open_no_pr[:15]
        ],  # fmt: skip
        "drift": [
            {
                "issue": d["ticket"],
                "title": d["ticket_title"],
                "url": d["ticket_url"],
                "issue_says": (d["ticket_text"] or "")[:400],
                "comment": plain(d["message_text"]),
                "comment_url": d["message_url"],
                "by": d["changed_by"],
                "at": d["changed_at"],
                "stale_prs": [x["pr"] for x in d["stale_prs"]],
                "label": known.get(d["message_url"]),
            }
            for d in drift
        ],
        "graph": _graph(chains[:14], decisions[:6]),
        "note": NOTE,
    }


def plain(text: str) -> str:
    """A comment's markdown as one line of text: no headings, emphasis, table rules or code fences."""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"^\s*#+\s*|\*\*|__|`", "", t, flags=re.M)
    t = re.sub(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", " ", t)
    return re.sub(r"\s+", " ", t.replace("|", " ")).strip()


def _graph(chains: list[dict], decisions: list[dict]) -> dict:
    """Layered: people | decisions | issues | PRs."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, typ: str, col: int, status: str | None = None):
        nodes.setdefault(nid, {"id": nid, "label": label, "type": typ, "col": col, **({"status": status} if status else {})})

    for c in chains:
        node(c["issue"], f"{c['issue'].replace('GH-', '#')} {c['issue_title'][:48]}", "Ticket", 2, "shipped" if c["pr_state"] == "merged" else None)
        node(f"PR-{c['pr']}", f"PR #{c['pr']} {c['pr_title'][:44]}", "PullRequest", 3)
        edges.append({"from": f"PR-{c['pr']}", "to": c["issue"], "rel": "REFERENCES"})
        node(f"p:{c['pr_by']}", c["pr_by"], "Person", 0)
        edges.append({"from": f"p:{c['pr_by']}", "to": f"PR-{c['pr']}", "rel": "AUTHORED"})
        if c["opened_by"]:
            node(f"p:{c['opened_by']}", c["opened_by"], "Person", 0)
            edges.append({"from": f"p:{c['opened_by']}", "to": c["issue"], "rel": "OPENED"})
    for d in decisions:
        rid = d["requirement"]
        node(rid, plain(d["requirement_text"])[:60], "Requirement", 1)
        node(f"p:{d['by']}", d["by"], "Person", 0)
        node(d["issue"], f"{d['issue'].replace('GH-', '#')} {d['issue_title'][:48]}", "Ticket", 2)
        edges += [{"from": f"p:{d['by']}", "to": rid, "rel": "DECIDED"}, {"from": rid, "to": d["issue"], "rel": "AMENDS"}]
        edges += [{"from": f"PR-{n}", "to": rid, "rel": "IMPLEMENTS"} for n in d["implemented_by"] if f"PR-{n}" in nodes]
    unique = {(e["from"], e["to"], e["rel"]): e for e in edges}
    return {"nodes": list(nodes.values()), "edges": list(unique.values())}


# ---------------------------------------------------------------- jobs and cache

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="try")


def _path(org: str) -> Path:
    return CACHE / f"{org}.json"


def cached(repo: str) -> dict | None:
    """A built result still within its TTL, whose graph still exists."""
    from graph.db import get_db, org_graph_name

    org = org_for(repo)
    f = _path(org)
    if not f.exists():
        return None
    try:
        out = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - out.get("built_ts", 0) > TTL_H * 3600 or org_graph_name(org) not in get_db().list_graphs():
        return None
    return out


def _evict() -> None:
    """Keeps at most MAX_REPOS repo graphs: the least recently built go first."""
    from graph.db import get_db, get_graph, org_graph_name

    files = sorted(CACHE.glob("gh-*.json"), key=lambda f: f.stat().st_mtime)
    for f in files[: max(0, len(files) - MAX_REPOS)]:
        name = org_graph_name(f.stem)
        if name in get_db().list_graphs():
            get_graph(name).delete()
        f.unlink(missing_ok=True)


def _run(repo: str, fallback_snapshot: bool = False) -> None:
    org = org_for(repo)
    job = _jobs[repo]
    t0 = time.time()

    def step(s: str) -> None:
        job["step"] = s

    try:
        try:
            snap = fetch(repo, step)
        except (TryError, requests.RequestException):
            fallback = from_snapshot(repo) if fallback_snapshot else None
            if fallback is None:
                raise
            snap = fallback
        step("Building the graph (rules extractor)")
        out = build(snap, org)
        out |= {"org": org, "built_ts": time.time(), "build_seconds": round(time.time() - t0, 1)}
        CACHE.mkdir(parents=True, exist_ok=True)
        _path(org).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        _evict()
        job.update(state="ready", step="Done")
    except TryError as e:
        job.update(state="error", error=str(e))
    except Exception as e:  # noqa: BLE001 - shown to the person who asked, logged for us
        import logging

        logging.getLogger("try").exception("try %s failed", repo)
        job.update(state="error", error=f"Building the graph failed: {type(e).__name__}.")


def request(text: str) -> dict:
    """Starts (or reuses) a build. Returns the result when it's ready, else the job's state."""
    repo = parse(text)
    hit = cached(repo)
    if hit:
        return {"state": "ready", "repo": hit["repo"], "org": hit["org"], "result": hit}
    with _lock:
        job = _jobs.get(repo)
        if job and job["state"] in ("queued", "running"):
            return {"state": job["state"], "repo": repo, "org": org_for(repo), "step": job.get("step"), "since": job["started"]}
        busy = sum(1 for j in _jobs.values() if j["state"] in ("queued", "running"))
        if busy >= 6:
            raise TryError("A few repos are being built right now; try again in a minute.")
        _jobs[repo] = {"state": "queued", "step": "Waiting for a free builder", "started": time.time()}

    def go():
        _jobs[repo]["state"] = "running"
        _run(repo)

    _pool.submit(go)
    return {"state": "queued", "repo": repo, "org": org_for(repo), "step": _jobs[repo]["step"], "since": _jobs[repo]["started"]}


def status(text: str) -> dict:
    repo = parse(text)
    hit = cached(repo)
    if hit:
        return {"state": "ready", "repo": hit["repo"], "org": hit["org"], "result": hit}
    job = _jobs.get(repo)
    if not job:
        return {"state": "none", "repo": repo, "org": org_for(repo)}
    return {"state": job["state"], "repo": repo, "org": org_for(repo), "step": job.get("step"), "error": job.get("error"), "since": job["started"]}


def recent(limit: int = 8) -> list[dict]:
    """Repos with a fresh result, newest first (the page offers them as one-click examples)."""
    out = []
    for f in sorted(CACHE.glob("gh-*.json"), key=lambda f: -f.stat().st_mtime) if CACHE.exists() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if time.time() - r.get("built_ts", 0) <= TTL_H * 3600:
            out.append({"repo": r["repo"], "org": r["org"], "counts": r["counts"], "fetched_at": r["fetched_at"]})
        if len(out) >= limit:
            break
    return out


def prewarm(stop: threading.Event | None = None) -> None:
    """Builds TRY_PREWARM (FalkorDB/FalkorDB) at startup unless a fresh result exists, so the first click is instant.
    Falls back to the bundled snapshot when GitHub can't be reached."""
    for repo in PREWARM:
        if stop is not None and stop.is_set():
            return
        try:
            repo = parse(repo)
        except TryError:
            continue
        if cached(repo):
            continue
        _jobs[repo] = {"state": "running", "step": "Pre-warming", "started": time.time()}
        _run(repo, fallback_snapshot=True)


def start(stop: threading.Event) -> None:
    import sys

    if "pytest" in sys.modules or os.getenv("TRY_PREWARM_OFF"):
        return
    threading.Thread(target=prewarm, args=(stop,), daemon=True, name="try-prewarm").start()
