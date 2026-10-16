"""Sprint retro report: what we decided, what we shipped, where they diverge. Every line carries a source link.

python -m agent.retro s1
"""

import sys

from agent.tools import drift_path
from graph import queries as Q
from graph.db import get_graph


def retro(sprint: str, g=None) -> dict:
    g = g or get_graph()
    s = Q.rows(g, "MATCH (s:Sprint {id: $id}) RETURN s.name AS name, s.start AS start, s.end AS end, s.start_ms AS a, s.end_ms AS b", id=sprint)
    if not s:
        raise ValueError(f"unknown sprint {sprint}")
    s = s[0]
    decided = Q.rows(g, Q.SPRINT_DECISIONS, sprint=sprint)
    shipped = Q.rows(g, Q.SPRINT_SHIPPED, sprint=sprint)
    # Divergence: drift whose change happened up to the end of this sprint and is still open
    diverged = [d for d in Q.drift(g) if d["changed_ms"] <= s["b"]]
    for d in diverged:
        d["path"] = drift_path(d)
    return {"sprint": sprint, "name": s["name"], "start": s["start"], "end": s["end"], "decided": decided, "shipped": shipped, "diverged": diverged}


def to_markdown(r: dict) -> str:
    out = [f"# {r['name']} retro ({r['start'][:10]} to {r['end'][:10]})", "", "## What we decided"]
    if not r["decided"]:
        out.append("_No decisions recorded in chat._")
    for d in r["decided"]:
        if d.get("dismissed_by"):
            status = f"dismissed by {d['dismissed_by']}"
        elif d["shipped_in"]:
            status = "shipped in " + ", ".join(f"#{n}" for n in d["shipped_in"])
        elif d["superseded_by"] == "ticket":
            status = "written into ticket, not shipped yet"
        elif d["superseded_by"]:
            status = "replaced by a later change"
        else:
            status = "NOT in ticket, NOT shipped"
        if d["superseded_by"] == "ticket" and d["shipped_in"]:
            status = "written into ticket, " + status
        out.append(
            f"- {d['at'][:10]} **{d['by']}** ({d['feature']}, {d['ticket']}): {d['text']} [{status}] " f"([{d['platform']}#{d['channel']}]({d['source']}))"
        )
    out += ["", "## What we shipped"]
    for p in r["shipped"]:
        tickets = ", ".join(p["tickets"]) or "no ticket"
        how = "" if p["link"] == ["hard"] else f" _(linked by {', '.join(p['link'])})_"
        out.append(f"- [PR #{p['pr']}]({p['url']}) {p['title']} by {p['author']} ({tickets}){how}")
    out += ["", "## Where they diverge"]
    if not r["diverged"]:
        out.append("_No open drift._ ✅")
    for d in r["diverged"]:
        stale = ", ".join(f"[#{x['pr']}]({x['url']})" for x in d["stale_prs"] if x["pr"] is not None) or "none"
        out.append(
            f"- ⚠️ **{d['feature_name']}**: on {d['changed_at'][:10]} {d['changed_by']} decided "
            f"\"{d['requirement_text']}\" ([{d['source']}#{d['channel']}]({d['message_url']})), "
            f"but [{d['ticket']}]({d['ticket_url']}) still says \"{d['ticket_text']}\". Stale PRs: {stale}."
        )
        out.append(f"  - path: `{d['path']}`")
    return "\n".join(out)


if __name__ == "__main__":
    print(to_markdown(retro(sys.argv[1] if len(sys.argv) > 1 else "s1")))
