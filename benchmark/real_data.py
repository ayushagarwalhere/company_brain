"""Real-data sanity check: the unchanged pipeline on a public GitHub repo it was never tuned on.

    python -m benchmark.real_data fetch --repo FalkorDB/FalkorDB   # snapshot -> data/real/<repo>.json.gz
    python -m benchmark.real_data run --repo FalkorDB/FalkorDB     # separate graph, flags -> benchmark/results/
    python -m benchmark.real_data score      # precision of all flags against benchmark/real_data_labels.json

Repos, both fixed before looking at any output: FalkorDB/FalkorDB (the sponsor's repo) and, because it
produced only 5 flags, excalidraw/excalidraw (a product repo whose issues are feature discussions).

Mapping (the only adapter code; no rule, threshold or extractor is changed for this run):
  issue          -> Ticket "GH-<n>": title, body (one version: REST has no body-edit history), labels,
                    first assignee, closed_at as completion
  issue comment  -> Message in channel "issue-<n>", hard-linked (MENTIONS) to its issue
  pull request   -> PullRequest; "#<n>" / "fixes #<n>" become GH-<n> so the hard-link signal can see them
Comments on PRs are not ingested (they discuss code, not requirements).
"""
import argparse
import gzip
import json
import re
import time
from pathlib import Path

import requests

from pipeline.events import Event

ROOT = Path(__file__).resolve().parent.parent
REPO = "FalkorDB/FalkorDB"
ITEMS = 400                  # most recent issues + PRs
COMMENT_PAGES = 25           # unauthenticated GitHub API: 60 requests/hour
HASH_REF = re.compile(r"(?<![\w/&])#(\d{1,6})\b")


def snapshot_path(repo: str = REPO) -> Path:
    return ROOT / "data" / "real" / (repo.replace("/", "__") + ".json.gz")


def load_snapshot(repo: str = REPO) -> dict:
    return json.loads(gzip.decompress(snapshot_path(repo).read_bytes()))


def gh_ids(text: str) -> str:
    """'#123' -> 'GH-123' so the existing ticket-id regex links it."""
    return HASH_REF.sub(lambda m: f"GH-{m.group(1)}", text or "")


# ---------------------------------------------------------------- fetch

def _get(url, params):
    for i in range(4):
        r = requests.get(url, params=params, headers={"Accept": "application/vnd.github+json"}, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            raise SystemExit(f"GitHub rate limit hit; resets at {r.headers.get('X-RateLimit-Reset')}")
        time.sleep(2 ** i)
    r.raise_for_status()


def fetch(repo: str = REPO, items: int = ITEMS) -> dict:
    base = f"https://api.github.com/repos/{repo}"
    issues = []
    for page in range(1, items // 100 + 1):
        issues += _get(f"{base}/issues", {"state": "all", "per_page": 100, "page": page, "sort": "created", "direction": "desc"})
    since = min(i["created_at"] for i in issues)
    comments, page = [], 1
    while page <= COMMENT_PAGES:
        batch = _get(f"{base}/issues/comments", {"since": since, "per_page": 100, "page": page, "sort": "created", "direction": "asc"})
        comments += batch
        if len(batch) < 100:
            break
        page += 1
    keep_i = ("number", "title", "body", "state", "labels", "assignees", "user", "created_at", "closed_at", "html_url", "pull_request")
    snap = {"repo": repo, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "issues": [{k: i.get(k) for k in keep_i} for i in issues],
            "comments": [{"id": c["id"], "issue_url": c["issue_url"], "user": c["user"]["login"], "body": c["body"],
                          "created_at": c["created_at"], "html_url": c["html_url"]} for c in comments]}
    for i in snap["issues"]:  # trim to what the adapter uses
        i["labels"] = [l["name"] for l in i["labels"] or []]
        i["assignees"] = [a["login"] for a in i["assignees"] or []]
        i["user"] = i["user"]["login"]
        i["merged_at"] = (i.pop("pull_request") or {}).get("merged_at", None) if i.get("pull_request") is not None else None
        i["is_pr"] = i["merged_at"] is not None or "/pull/" in (i["html_url"] or "")
    return snap


# ---------------------------------------------------------------- adapter

def to_events(snap: dict) -> tuple[list[Event], list[Event], list[Event]]:
    issues = [i for i in snap["issues"] if not i["is_pr"]]
    prs = [i for i in snap["issues"] if i["is_pr"]]
    numbers = {i["number"] for i in issues}
    tickets = [Event(source="tickets", kind="ticket", id=f"GH-{i['number']}", author=i["user"], ts=i["created_at"],
                     text=f"{i['title']}\n\n{gh_ids(i['body'])}", url=i["html_url"],
                     extra={"title": i["title"], "description": gh_ids(i["body"]), "state": i["state"],
                            "labels": i["labels"], "assignee": (i["assignees"] or [None])[0], "sprint": None,
                            "updated_at": i["closed_at"] or i["created_at"], "completed_at": i["closed_at"], "versions": []})
               for i in issues]
    messages = []
    for c in snap["comments"]:
        n = int(c["issue_url"].rsplit("/", 1)[1])
        if n not in numbers:
            continue  # PR comment, or an issue outside the snapshot window
        messages.append(Event(source="github", kind="message", id=f"ghc:{c['id']}", author=c["user"], ts=c["created_at"],
                              text=gh_ids(c["body"]), url=c["html_url"], channel=f"issue-{n}", extra={"issue": f"GH-{n}"}))
    pr_events = [Event(source="github", kind="pull_request", id=f"PR-{p['number']}", author=p["user"], ts=p["created_at"],
                       text=f"{p['title']}\n\n{gh_ids(p['body'])}", url=p["html_url"],
                       extra={"number": p["number"], "title": p["title"], "body": gh_ids(p["body"]),
                              "state": "merged" if p["merged_at"] else p["state"], "merged_at": p["merged_at"]})
                 for p in prs]
    return tickets, messages, pr_events


# ---------------------------------------------------------------- run / score

def graph_name(repo: str) -> str:
    return "realdata_" + repo.split("/")[1].lower()


def build(snap: dict, graph: str):
    from graph import writer
    from graph.db import get_graph
    from pipeline.resolve import resolve
    g = get_graph(graph)
    try:
        g.delete()
    except Exception:
        pass
    g = get_graph(graph)
    writer.apply_schema(g)
    tickets, messages, prs = to_events(snap)
    writer.write_tickets(g, tickets)
    writer.write_messages(g, messages)
    g.query("""UNWIND $ps AS p MATCH (m:Message {id: p.m}), (t:Ticket {id: p.t}) MERGE (m)-[:MENTIONS]->(t)""",
            {"ps": [{"m": m.id, "t": m.extra["issue"]} for m in messages]})
    writer.write_pull_requests(g, prs)
    stats = resolve(g, "heuristic", log=lambda *_: None)
    return g, {"issues": len(tickets), "comments": len(messages), "prs": len(prs),
               "features": len(stats["features"]), "chat_changes": len(stats["changes"]),
               "messages_linked": len(stats["msg_feature"]), "implements": len(stats["implements"])}


def flags_path(repo: str) -> Path:
    return ROOT / "benchmark" / "results" / f"real_data_flags_{repo.split('/')[1].lower()}.json"


def run(repo: str = REPO):
    from graph.queries import drift
    snap = load_snapshot(repo)
    g, stats = build(snap, graph_name(repo))
    flags = [{"requirement": d["requirement"], "ticket": d["ticket"], "ticket_title": d["ticket_title"],
              "ticket_url": d["ticket_url"], "feature": d["feature_name"], "message_url": d["message_url"],
              "changed_by": d["changed_by"], "changed_at": d["changed_at"], "extracted_requirement": d["requirement_text"],
              "comment": d["message_text"], "issue_body_head": (d["ticket_text"] or "")[:600]} for d in drift(g)]
    out = {"repo": snap["repo"], "fetched_at": snap["fetched_at"], "extractor": "heuristic (rules, no LLM)",
           "stats": {**stats, "drift_flags": len(flags)}, "flags": flags}
    flags_path(repo).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out["stats"], indent=1))
    return out


SAMPLE_SEED, SAMPLE_SIZE = 0, 20


def decision_sample(repos=("FalkorDB/FalkorDB", "excalidraw/excalidraw")) -> dict:
    """The step that creates drift, on more data: every real comment (issue AND PR comments) the
    rules extractor calls a decision, then a fixed-seed random sample of them for hand labelling."""
    import random
    from pipeline.extract import HeuristicExtractor
    ex, total, hits = HeuristicExtractor(), 0, []
    for repo in repos:
        snap = load_snapshot(repo)
        items = [{"id": c["html_url"], "text": c["body"] or "", "thread": []} for c in snap["comments"]]
        total += len(items)
        body = {c["html_url"]: c["body"] for c in snap["comments"]}
        hits += [{"repo": repo, "url": k, "comment": body[k], "extracted_requirement": v["requirement"]}
                 for k, v in ex.classify(items, []).items() if v["kind"] == "decision"]
    hits.sort(key=lambda h: h["url"])
    sample = random.Random(SAMPLE_SEED).sample(hits, min(SAMPLE_SIZE, len(hits)))
    out = {"comments": total, "classified_decision": len(hits), "seed": SAMPLE_SEED, "sample": sample}
    (ROOT / "benchmark" / "results" / "real_data_decision_sample.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(hits)} of {total} comments classified as decisions; sampled {len(sample)}")
    return out


RECALL_SEED, RECALL_SIZE = 1, 30
PROPOSALS = ("golang/go", "Proposal-Accepted")  # a tracker where decisions really are made in comments


def fetch_labelled_issues(repo: str, label: str, n_issues: int = 20, max_comments: int = 40) -> dict:
    """Snapshot the most recently updated issues with `label` (and at most `max_comments` comments) plus
    all their comments. For golang/go accepted proposals the review group's decisions are comments."""
    base = f"https://api.github.com/repos/{repo}"
    issues = [i for i in _get(f"{base}/issues", {"labels": label, "state": "all", "per_page": 50, "sort": "updated"})
              if "pull_request" not in i and 0 < i["comments"] <= max_comments][:n_issues]
    comments = []
    for i in issues:
        for c in _get(f"{base}/issues/{i['number']}/comments", {"per_page": 100}):
            comments.append({"id": c["id"], "issue_url": c["issue_url"], "user": c["user"]["login"], "body": c["body"],
                             "created_at": c["created_at"], "html_url": c["html_url"]})
    return {"repo": repo, "label": label, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "issues": [{"number": i["number"], "title": i["title"], "body": i["body"], "user": i["user"]["login"],
                        "state": i["state"], "html_url": i["html_url"], "is_pr": False, "labels": [l["name"] for l in i["labels"]],
                        "assignees": [], "created_at": i["created_at"], "closed_at": i["closed_at"], "merged_at": None}
                       for i in issues],
            "comments": comments}


def proposals_path() -> Path:
    return ROOT / "data" / "real" / "golang__go__proposals.json.gz"


def proposal_sample() -> list[dict]:
    """30 random comments (seed 2) from the accepted-proposal snapshot: an ENRICHED pool, chosen because
    decisions happen there, so recall can be estimated at all."""
    import random
    snap = json.loads(gzip.decompress(proposals_path().read_bytes()))
    issues = {i["number"]: i for i in snap["issues"]}
    pool = [{"repo": snap["repo"], "url": c["html_url"], "issue": int(c["issue_url"].rsplit("/", 1)[1]),
             "issue_title": issues[int(c["issue_url"].rsplit("/", 1)[1])]["title"], "author": c["user"], "comment": c["body"]}
            for c in snap["comments"] if c["body"]]
    pool.sort(key=lambda c: c["url"])
    return random.Random(2).sample(pool, min(30, len(pool)))


def recall_sample(repos=("FalkorDB/FalkorDB", "excalidraw/excalidraw")) -> list[dict]:
    """A fixed-seed random sample of issue comments (not PR review) for labelling BOTH ways, so recall
    can be estimated: precision alone only looks at what the extractor flagged."""
    import random
    pool = []
    for repo in repos:
        snap = load_snapshot(repo)
        issues = {i["number"]: i for i in snap["issues"] if not i["is_pr"]}
        for c in snap["comments"]:
            n = int(c["issue_url"].rsplit("/", 1)[1])
            if n in issues and c["body"]:
                pool.append({"repo": repo, "url": c["html_url"], "issue": n, "issue_title": issues[n]["title"],
                             "issue_author": issues[n]["user"], "author": c["user"], "comment": c["body"]})
    pool.sort(key=lambda c: c["url"])
    return random.Random(RECALL_SEED).sample(pool, min(RECALL_SIZE, len(pool)))


def classify_sample(items: list[dict], extractor: str) -> dict[str, dict]:
    """Extraction only (no features, no thread): the same call the pipeline makes per message."""
    from pipeline.extract import get_extractor
    ex = get_extractor(extractor)
    return ex.classify([{"id": it["url"], "author": it.get("author", ""), "ts": "", "text": it["comment"], "thread": []}
                        for it in items], [])


def extraction_eval(extractor: str) -> dict:
    """Extraction on real text, against both hand-labelled sets:
      * the 25 items the RULES flagged, all labelled false: how many does this extractor still call a change?
      * the 60-comment recall sample (30 random issue comments + 30 from accepted Go proposals):
        precision and recall of "is a requirement change"."""
    from pipeline.extract import CHANGE_KINDS
    flagged = json.loads((ROOT / "benchmark" / "real_data_labels.json").read_text(encoding="utf-8"))["labels"]
    texts = {}
    for repo in ("FalkorDB/FalkorDB", "excalidraw/excalidraw"):
        texts.update({c["html_url"]: c["body"] for c in load_snapshot(repo)["comments"]})
    known_neg = [{"url": l["url"], "comment": texts[l["url"]]} for l in flagged]
    recall_items = recall_sample() + proposal_sample()
    gold = {l["url"]: l["is_requirement_change"] for l in json.loads(
        (ROOT / "benchmark" / "real_data_recall_labels.json").read_text(encoding="utf-8"))["labels"]}
    cls = classify_sample(known_neg + recall_items, extractor)
    is_change = {u: c.get("kind") in CHANGE_KINDS and bool(c.get("requirement")) for u, c in cls.items()}
    out = {"extractor": extractor,
           "known_false_positives_still_flagged": f"{sum(is_change[i['url']] for i in known_neg)} / {len(known_neg)}"}
    for name, items in (("issue_comments", recall_items[:30]), ("go_proposals", recall_items[30:]), ("all_60", recall_items)):
        tp = sum(is_change[i["url"]] and gold[i["url"]] for i in items)
        fp = sum(is_change[i["url"]] and not gold[i["url"]] for i in items)
        fn = sum(not is_change[i["url"]] and gold[i["url"]] for i in items)
        out[name] = {"positives": tp + fn, "flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                     "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                     "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    out["guarded"] = sum(1 for c in cls.values() if c.get("guard"))
    out["errors"] = sum(1 for c in cls.values() if c.get("kind") == "error")
    return out


def score(labels_path: Path = ROOT / "benchmark" / "real_data_labels.json") -> dict:
    """Precision per labelled set (end-to-end drift flags; sampled decision classifications) and overall."""
    labels = json.loads(labels_path.read_text(encoding="utf-8"))["labels"]

    def summary(ls):
        tp = sum(1 for l in ls if l["verdict"] != "false_positive")
        patterns: dict[str, int] = {}
        for l in ls:
            if l["verdict"] == "false_positive":
                patterns[l["pattern"]] = patterns.get(l["pattern"], 0) + 1
        return {"labelled": len(ls), "true_positive": tp, "precision": round(tp / len(ls), 3) if ls else None,
                "failure_patterns": dict(sorted(patterns.items(), key=lambda kv: (-kv[1], kv[0])))}

    out = {s: summary([l for l in labels if l["set"] == s]) for s in sorted({l["set"] for l in labels})}
    out["all"] = summary(labels)
    print(json.dumps(out, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "fetch-proposals", "run", "sample", "score", "extraction"])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--extractor", default="heuristic", choices=["heuristic", "llm"])
    a = ap.parse_args()
    if a.cmd == "fetch":
        snap = fetch(a.repo)
        p = snapshot_path(a.repo)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(gzip.compress(json.dumps(snap, ensure_ascii=False).encode("utf-8")))
        print(f"{len(snap['issues'])} issues/PRs, {len(snap['comments'])} comments -> {p}")
    elif a.cmd == "run":
        run(a.repo)
    elif a.cmd == "sample":
        decision_sample()
    elif a.cmd == "fetch-proposals":
        snap = fetch_labelled_issues(*PROPOSALS)
        proposals_path().write_bytes(gzip.compress(json.dumps(snap, ensure_ascii=False).encode("utf-8")))
        print(f"{len(snap['issues'])} issues, {len(snap['comments'])} comments -> {proposals_path()}")
    elif a.cmd == "extraction":
        from pipeline.llm import model_name
        out = extraction_eval(a.extractor)
        tag = "rules" if a.extractor == "heuristic" else "llm_" + model_name().replace(":", "-").replace("/", "-")
        out["model"] = None if a.extractor == "heuristic" else model_name()
        (ROOT / "benchmark" / "results" / f"real_extraction_{tag}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(json.dumps(out, indent=1))
    else:
        score()


if __name__ == "__main__":
    main()
