"""Graph tools the agent can call. Each returns {"rows": [...], "paths": [...]}.

`paths` are human-readable graph paths: the evidence shown next to every answer.
"""
from graph import queries as Q
from graph.db import get_graph
from pipeline.events import from_ms


def _g():
    return get_graph()


def drift_path(d: dict) -> str:
    p = (f"(Person {d['changed_by']})-[:POSTED]->(Message {d['message']} @ {d['source']}#{d['channel']}, {d['changed_at']})"
         f"-[:CHANGES]->(Requirement \"{d['requirement_text']}\")-[:AMENDS]->(Ticket {d['ticket']})"
         f"-[:ABOUT]->(Feature {d['feature']})")
    stale = [x for x in d["stale_prs"] if x["pr"] is not None]
    if stale:
        p += " ; " + " ; ".join(f"(PullRequest #{x['pr']})-[:REFERENCES]->(Ticket {d['ticket']})"
                                + (", merged after the decision but not matched to it (check)" if x.get("merged_after") else ", merged before the decision")
                                + (f", IMPLEMENTS older \"{x['implements']}\"" if x.get("implements") else "")
                                for x in stale)
    for doc in d.get("stale_docs", []):
        p += f" ; (Document {doc['id']} \"{doc['title']}\", updated {(doc['updated'] or '')[:10]})-[:MENTIONS]->(Ticket {d['ticket']}), older than the change"
    return p


def list_features() -> dict:
    rows = Q.rows(_g(), """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                           RETURN f.id AS id, f.name AS name, collect(t.id) AS tickets ORDER BY f.id""")
    return {"rows": rows, "paths": [f"(Feature {r['id']}) <-[:ABOUT]- tickets {r['tickets']}" for r in rows]}


def drift_for_feature(feature: str | None = None) -> dict:
    rows = Q.drift(_g(), feature=feature)
    return {"rows": rows, "paths": [drift_path(d) for d in rows]}


def decision_history(feature: str) -> dict:
    rows = Q.rows(_g(), Q.DECISION_HISTORY, feature=feature)
    paths = []
    for r in rows:
        rel = "STATES" if r["origin"] == "ticket" else "CHANGES"
        p = f"({r['source_type']} {r['source_id']})-[:{rel}]->(Requirement {r['requirement']} @ {r['at']})"
        if r["supersedes"]:
            p += f"-[:SUPERSEDES]->(Requirement {r['supersedes']})"
        if r["implemented_by"]:
            p += f" <-[:IMPLEMENTS]- PR {r['implemented_by']}"
        paths.append(p)
    return {"rows": rows, "paths": paths}


def feature_timeline(feature: str) -> dict:
    rows = Q.rows(_g(), Q.FEATURE_TIMELINE, feature=feature)
    for r in rows:
        r["at"] = from_ms(r.pop("at"))
    rows = [r for r in rows if r["type"] != "Message" or len(r["text"] or "") > 25][:60]
    return {"rows": rows, "paths": [f"({r['type']} {r['id']})-[:ABOUT]->(Feature {feature})" for r in rows]}


def who_knows(feature: str) -> dict:
    rows = Q.rows(_g(), Q.WHO_KNOWS, feature=feature)
    return {"rows": rows, "paths": [f"(Person {r['person']})-[:POSTED|AUTHORED|MADE]->({r['items']} items)-[:ABOUT]->(Feature {feature})"
                                    for r in rows]}


def decision_impact(decision: str) -> dict:
    rows = Q.rows(_g(), Q.DECISION_IMPACT, decision=decision)
    return {"rows": rows, "paths": [f"(Decision {decision})-[:CHANGES]->(Requirement)-[:AMENDS]->(Ticket {r['ticket']}) "
                                    f"<-[:REFERENCES]- PRs {r['prs']}; owner {r['owner']}" for r in rows]}


def list_decisions(feature: str | None = None) -> dict:
    rows = Q.rows(_g(), """MATCH (p:Person)-[:MADE]->(d:Decision)-[:CHANGES]->(r:Requirement)-[:ABOUT]->(f:Feature)
                           WHERE $feature IS NULL OR f.id = $feature
                           MATCH (d)-[:RECORDED_IN]->(m:Message)
                           RETURN d.id AS id, d.text AS text, d.at AS at, p.id AS by, f.id AS feature,
                                  m.source AS platform, m.channel AS channel, m.url AS url ORDER BY d.at_ms""",
                  feature=feature)
    return {"rows": rows, "paths": [f"(Person {r['by']})-[:MADE]->(Decision {r['id']})-[:RECORDED_IN]->(Message @ {r['platform']}#{r['channel']})"
                                    for r in rows]}


def how_connected(a: str, b: str) -> dict:
    """Shortest causal chain between two ids (person, message, ticket BD-.., PR-n, decision dec:..)."""
    rows = Q.connection(_g(), a, b)
    paths = []
    for r in rows:
        parts = [f"({r['nodes'][0]['type']} {r['nodes'][0]['id']})"]
        for i, rel in enumerate(r["rels"]):
            nxt = r["nodes"][i + 1]
            forward = r["starts"][i] == r["nodes"][i]["id"]
            parts.append((f"-[:{rel}]->" if forward else f"<-[:{rel}]-") + f"({nxt['type']} {nxt['id']})")
        paths.append("".join(parts))
    return {"rows": rows, "paths": paths}

def feature_prs(feature: str) -> dict:
    """PRs about a feature: their ticket, how the link was made, author, merge date, what they implement."""
    rows = Q.rows(_g(), """MATCH (pr:PullRequest)-[:ABOUT]->(:Feature {id: $f}) MATCH (a:Person)-[:AUTHORED]->(pr)
                           OPTIONAL MATCH (pr)-[ref:REFERENCES]->(t:Ticket)
                           OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(r:Requirement)
                           RETURN pr.number AS pr, pr.title AS title, pr.url AS url, a.id AS author, pr.merged AS merged,
                                  collect(DISTINCT t.id) AS tickets, collect(DISTINCT coalesce(ref.how, 'hard')) AS link,
                                  collect(DISTINCT r.id) AS implements, pr.number AS n ORDER BY n""", f=feature)
    return {"rows": rows, "paths": [f"(PullRequest #{r['pr']})-[:REFERENCES {{via: {', '.join(r['link'])}}}]->(Ticket {', '.join(r['tickets']) or '?'})"
                                    for r in rows]}

TOOLS = {
    "list_features": (list_features, "List all features with their tickets. Call first to find feature ids.", {}),
    "drift_for_feature": (drift_for_feature, "Requirements changed in chat that the ticket/PRs don't reflect. Omit feature for all.",
                          {"feature": {"type": "string", "description": "feature id, optional"}}),
    "decision_history": (decision_history, "How a feature's requirements evolved: every ticket version and chat change, what superseded what, which PR implements which.",
                         {"feature": {"type": "string"}}),
    "feature_timeline": (feature_timeline, "Chronological messages, tickets, PRs and requirements for a feature.",
                         {"feature": {"type": "string"}}),
    "who_knows": (who_knows, "People ranked by involvement with a feature (decisions, PRs, tickets, messages).",
                  {"feature": {"type": "string"}}),
    "list_decisions": (list_decisions, "Decisions made in chat, optionally for one feature, with who made them and where.",
                       {"feature": {"type": "string", "description": "feature id, optional"}}),
    "feature_prs": (feature_prs, "Pull requests for a feature: ticket, how the link was resolved (hard id vs. proximity), author, merge date, implemented requirement.",
                    {"feature": {"type": "string"}}),
    "how_connected": (how_connected, "Shortest causal chain linking two things, e.g. a person and a PR ('liam', 'PR-6') or a message and a ticket. Ids: person ids, message ids, BD-xxx, PR-n, dec:<message id>.",
                      {"a": {"type": "string"}, "b": {"type": "string"}}),
    "decision_impact": (decision_impact, "Downstream impact of a decision: ticket, owner, PRs, related tickets.",
                        {"decision": {"type": "string", "description": "decision id like dec:m_exp_12"}}),
}


def openai_schema() -> list[dict]:
    out = []
    for name, (_, desc, props) in TOOLS.items():
        required = [k for k, v in props.items() if "optional" not in v.get("description", "")]
        out.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}})
    return out


def call(name: str, args: dict) -> dict:
    fn = TOOLS[name][0]
    return fn(**{k: v for k, v in (args or {}).items() if k in TOOLS[name][2]})
