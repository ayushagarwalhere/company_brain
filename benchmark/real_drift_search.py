"""Search a real repo's issue comments for drift candidates, then verify each by hand.

    python -m benchmark.real_drift_search --repo FalkorDB/FalkorDB
    python -m benchmark.real_drift_search --repo excalidraw/excalidraw --standing-only

Uses the committed snapshot in data/real/ and the configured LLM extractor, unchanged (the same per-message call as
`benchmark.real_data extraction`). In scope: comments on issues (not PR review comments), not by bots. With
--standing-only, only comments by someone with standing on the issue (its author or assignee, or a maintainer = the
author of a merged PR in the snapshot), which is the pipeline's decision-rights rule applied before the LLM to fit a
free tier's token cap.

Each comment the extractor calls a decision or requirement change is a *candidate*. Whether it is real drift (an
agreed change that the issue and later PRs do not reflect) is decided by reading the GitHub thread, and recorded in
the result file as `verdict` / `why` / `links`; re-running keeps those.
"""

import argparse
import gzip
import json

from benchmark.real_data import classify_sample
from config import MIN_CONFIDENCE
from pipeline.extract import CHANGE_KINDS
from pipeline.llm import model_name

ROOT_RESULTS = "benchmark/results"


def comments_in_scope(repo: str, standing_only: bool) -> tuple[dict, list[dict]]:
    d = json.load(gzip.open(f"data/real/{repo.replace('/', '__')}.json.gz"))
    issues = {x["number"]: x for x in d["issues"]}
    maintainers = {x["user"] for x in d["issues"] if x.get("is_pr") and x.get("merged_at")}

    def num(c):
        return int(c["issue_url"].rstrip("/").split("/")[-1])

    out = []
    for c in d["comments"]:
        i = issues.get(num(c))
        if (i and i.get("is_pr")) or (c.get("user") or "").endswith("[bot]"):
            continue
        if standing_only:
            owners = ({i["user"]} | set(i.get("assignees") or [])) if i else set()
            if c["user"] not in owners and c["user"] not in maintainers:
                continue
        out.append({**c, "issue": num(c)})
    return d, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--standing-only", action="store_true")
    a = ap.parse_args()
    d, scope = comments_in_scope(a.repo, a.standing_only)
    cls = classify_sample([{"url": c["html_url"], "author": c["user"], "comment": c["body"]} for c in scope], "llm")
    errors = sum(1 for v in cls.values() if v.get("kind") == "error")
    path = f"{ROOT_RESULTS}/real_drift_search_{a.repo.split('/')[1].lower()}.json"
    try:
        old = {f["url"]: f for f in json.load(open(path, encoding="utf-8")).get("flagged", [])}
    except FileNotFoundError:
        old = {}
    flagged = []
    for u, v in cls.items():
        if v.get("kind") in CHANGE_KINDS and (v.get("confidence") or 0) >= MIN_CONFIDENCE:
            c = next(x for x in scope if x["html_url"] == u)
            keep = {k: old[u][k] for k in ("verdict", "why", "links") if u in old and k in old[u]}
            flagged.append(
                {
                    "url": u,
                    "author": c["user"],
                    "created": c["created_at"],
                    "issue": c["issue"],
                    "kind": v["kind"],
                    "conf": v.get("confidence"),
                    "requirement": v.get("requirement"),
                    "comment": c["body"][:600],
                    **keep,
                }
            )
    out = {
        "repo": a.repo,
        "snapshot": d["fetched_at"],
        "model": model_name(),
        "filter": "issue comments, not PRs, not bots" + ("; by the issue author/assignee or a maintainer" if a.standing_only else ""),
        "comments": len(cls),
        "errors": errors,
        "flagged": flagged,
        "confirmed_drift": sum(1 for f in flagged if (f.get("verdict") or "").startswith("drift")),
        "unverified": sum(1 for f in flagged if not f.get("verdict")),
    }
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{a.repo}: {len(cls)} comments, {errors} failed calls, {len(flagged)} flagged, {out['unverified']} not yet verified -> {path}")
    for f in flagged:
        print(f"  {f['url']}  {f['author']}  {f['kind']} {f['conf']}  {f.get('verdict', '(verify by hand)')}")


if __name__ == "__main__":
    main()
