"""Spec generation: turns a drifted feature's graph context into an agent-ready spec.

The spec is written ONLY from what the graph returns (current requirement, history,
tickets, PRs and the code they touched). It stops at the spec: no agent executes it.

    python -m agent.spec feat_export
"""
import json
import sys

from agent.tools import decision_history, drift_for_feature
from config import settings
from graph import queries as Q
from graph.db import get_graph

SYSTEM = """You write implementation specs for coding agents. Use ONLY the JSON context given (from a knowledge graph).
Output Markdown with these sections:
# <Feature>: <one-line goal>
## Current requirement (source of truth)  - quote the newest requirement and cite its source message/date/person
## What exists today  - which PRs shipped what, and how it differs from the requirement
## Changes required  - numbered, concrete, testable
## Acceptance criteria  - checklist
## Out of scope / open questions
## Sources  - bullet list of message/ticket/PR ids from the context
Never invent requirements that are not in the context."""


def context(feature: str, g=None) -> dict:
    g = g or get_graph()
    feat = Q.rows(g, "MATCH (f:Feature {id: $f}) RETURN f.id AS id, f.name AS name", f=feature)
    if not feat:
        raise ValueError(f"unknown feature {feature}")
    tickets = Q.rows(g, """MATCH (t:Ticket)-[:ABOUT]->(:Feature {id: $f}) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person)
                           RETURN t.id AS id, t.title AS title, t.description AS description, t.state AS state, p.id AS owner
                           ORDER BY id""", f=feature)
    prs = Q.rows(g, """MATCH (pr:PullRequest)-[:ABOUT]->(:Feature {id: $f}) MATCH (a:Person)-[:AUTHORED]->(pr)
                       OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(r:Requirement)
                       RETURN pr.number AS number, pr.title AS title, pr.body AS body, pr.merged AS merged, a.id AS author,
                              collect(r.id) AS implements, pr.number AS n ORDER BY n""", f=feature)
    return {
        "feature": feat[0],
        "drift": [{k: d[k] for k in ("ticket", "requirement", "requirement_text", "changed_by", "changed_at",
                                     "message", "message_text", "source", "channel", "previous_requirement", "ticket_text")}
                  for d in drift_for_feature(feature)["rows"]],
        "history": decision_history(feature)["rows"],
        "tickets": tickets,
        "prs": prs,
    }


def _template(ctx: dict) -> str:
    f = ctx["feature"]
    out = [f"# {f['name']}: bring implementation in line with the latest decision", ""]
    if not ctx["drift"]:
        out.append("_No open drift for this feature: tickets and PRs match the latest requirement._")
    for d in ctx["drift"]:
        out += ["## Current requirement (source of truth)",
                f"> {d['requirement_text']}",
                f"Source: {d['message']} by {d['changed_by']} on {d['changed_at'][:10]} ({d['source']}#{d['channel']}).", "",
                "## What exists today",
                f"- Ticket {d['ticket']} still says: \"{d['ticket_text']}\""]
        out += [f"- PR #{p['number']} ({p['title']}) implements {', '.join(p['implements']) or 'no tracked requirement'}"
                for p in ctx["prs"]]
        out += ["", "## Changes required",
                f"1. Update {d['ticket']} to state: \"{d['requirement_text']}\"",
                "2. Change the implementation shipped in the PRs above to satisfy the new requirement.",
                "3. Add tests that cover the new behaviour.", "",
                "## Acceptance criteria",
                f"- [ ] {d['requirement_text']}",
                f"- [ ] {d['ticket']} description matches the requirement", ""]
    out += ["## Sources"] + [f"- {h['source_type']} {h['source_id']}" for h in ctx["history"] if h["source_id"]]
    return "\n".join(out)


def generate_spec(feature: str) -> dict:
    ctx = context(feature)
    if settings.deepseek_api_key and ctx["drift"]:
        from pipeline.llm import chat_text
        md = chat_text(SYSTEM, json.dumps(ctx, default=str, ensure_ascii=False))
        engine = "deepseek"
    else:
        md = _template(ctx)
        engine = "template"
    return {"feature": feature, "markdown": md, "engine": engine, "context": ctx}


if __name__ == "__main__":
    print(generate_spec(sys.argv[1] if len(sys.argv) > 1 else "feat_export")["markdown"])
