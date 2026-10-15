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
                                + (f", IMPLEMENTS older \"{x['implements']}\"" if x.get("implements") else ", implements nothing current")
                                for x in stale)
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
