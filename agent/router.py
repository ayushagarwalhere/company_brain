"""Rules-based graph agent: answers questions from graph tools without an LLM.

Same response shape as agent.agent.ask(), so the API, the bots and the dashboard
work with or without a DeepSeek key. Routing is explicit:

  entities  feature (TF-IDF over feature names + ticket titles, or a BD-id), person, PR-n, BD-n
  intent    connect · who-knows · drift · decided/shipped · history · impact · overview
"""
import re

from agent import tools
from graph import queries as Q
from graph.db import get_graph
from pipeline.textsim import TfIdf, tokens

INTENTS = [
    ("prs", re.compile(r"\b(which|what) (pr|pull request)s?\b|\bpull requests?\b|\bPRs\b", re.I)),
    ("connect", re.compile(r"\bconnect(ed|ion)?\b|\blink(ed)? between\b|\bpath (from|between)\b|→", re.I)),
    ("who", re.compile(r"\bwho\b.*\b(knows?|owns?|expert|worked|ask)\b|\bexpert", re.I)),
    ("impact", re.compile(r"\bimpact|\baffect(ed|s)?\b", re.I)),
    ("drift", re.compile(r"\bdrift|\bdiverg|\bout of (sync|date)|\bstale\b|\bmismatch", re.I)),
    ("decided", re.compile(r"\bdecid|\bdecision|\bship(ped)?\b|\bimplement|\bmatch(es)?\b|\bcurrent requirement|\bagreed\b", re.I)),
    ("history", re.compile(r"\bhistory|\btimeline|\bevolv|\bchanged?\b", re.I)),
]
ENTITY = re.compile(r"\b(PR-\d+|BD-\d+|#\d+)\b", re.I)


def _features(g):
    return Q.rows(g, """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                        RETURN f.id AS id, f.name AS name, collect(t.id) AS tickets, collect(t.title) AS titles""")


def _feature_for(q: str, feats: list[dict]) -> dict | None:
    for f in feats:
        if any(t.lower() in q.lower() for t in f["tickets"]):
            return f
    if not feats:
        return None
    sim = TfIdf({f["id"]: f"{f['name']} {f['name']} {' '.join(f['titles'])}" for f in feats})
    best, score = sim.best(q)
    return next((f for f in feats if f["id"] == best), None) if score >= 0.12 else None


def _people(g):
    return Q.rows(g, "MATCH (p:Person) RETURN p.id AS id, p.name AS name")


def _person_in(q: str, people: list[dict]) -> list[str]:
    words = set(tokens(q))
    return [p["id"] for p in people if p["id"] in words or (p["name"] or "").split(" ")[0].lower() in words]


def ask(question: str) -> dict:
    g = get_graph()
    feats, people = _features(g), _people(g)
    intent = next((name for name, rx in INTENTS if rx.search(question)), "overview")
    feature = _feature_for(question, feats)
    calls, paths, lines = [], [], []

    def run(name, **args):
        out = tools.call(name, args)
        calls.append({"tool": name, "args": args, "rows": len(out["rows"])})
        paths.extend(p for p in out["paths"] if p not in paths)
        return out["rows"]

    if intent == "connect":
        ents = [e.upper().replace("#", "PR-") for e in ENTITY.findall(question)]
        ids = _person_in(question, people) + ents
        if len(ids) >= 2:
            rows = run("how_connected", a=ids[0], b=ids[1])
            lines.append(f"{ids[0]} and {ids[1]} are {rows[0]['hops']} hops apart." if rows
                         else f"No causal path within 7 hops between {ids[0]} and {ids[1]}.")
        else:
            lines.append("Name two things to connect, e.g. a person and a PR: \"How is liam connected to PR-6?\"")

    elif intent == "prs" and feature:
        rows = run("feature_prs", feature=feature["id"])
        for r in rows:
            how = "" if r["link"] == ["hard"] else f", linked by {', '.join(r['link'])} (the PR never names its ticket)"
            lines.append(f"PR #{r['pr']} \"{r['title']}\" by {r['author']} → {', '.join(r['tickets']) or 'no ticket'}{how}.")

    elif intent == "who" and ENTITY.search(question):
        tid = ENTITY.search(question).group(1).upper()
        owner = Q.rows(g, "MATCH (t:Ticket {id: $t})-[:ASSIGNED_TO]->(p:Person) RETURN p.name AS name, p.role AS role", t=tid)
        if owner:
            lines.append(f"{tid} is owned by {owner[0]['name']} ({owner[0]['role']}).")
        for d in run("drift_for_feature", **({"feature": feature["id"]} if feature else {})):
            if d["ticket"] == tid:
                stale = ", ".join(f"#{p['pr']}" for p in d["stale_prs"] if p["pr"] is not None)
                lines.append(f"Their shipped work ({stale}) is stale because of {d['changed_by']}'s decision on "
                             f"{d['changed_at'][:10]}: \"{d['requirement_text']}\".")

    elif intent == "who" and feature:
        rows = run("who_knows", feature=feature["id"])
        top = rows[:3]
        lines.append(f"For {feature['name']}: " + "; ".join(
            f"{r['name']} ({r['role']}, {r['items']} items, score {int(r['score'])})" for r in top) + ".")

    elif intent == "impact" and feature:
        decs = run("list_decisions", feature=feature["id"])
        if decs:
            d = decs[-1]
            imp = run("decision_impact", decision=d["id"])
            for r in imp:
                lines.append(f"{d['by']}'s decision on {d['at'][:10]} (\"{d['text']}\") changes {r['ticket']} "
                             f"(owner {r['owner']}); PRs on it: {', '.join('#' + str(n) for n in r['prs']) or 'none'}; "
                             f"related tickets: {', '.join(r['related_tickets']) or 'none'}.")

    elif intent in ("drift", "decided", "history") or feature:
        drift = run("drift_for_feature", **({"feature": feature["id"]} if feature else {}))
        if intent in ("decided", "history") and feature:
            hist = run("decision_history", feature=feature["id"])
            seen, uniq = set(), []
            for h in hist:  # a requirement changed by both a Message and its Decision appears twice
                if h["requirement"] not in seen:
                    seen.add(h["requirement"])
                    uniq.append(h)
            by_super = {h["supersedes"]: h for h in uniq if h["supersedes"]}
            for h in (x for x in uniq if x["origin"] == "chat"):
                nxt = by_super.get(h["requirement"])
                if h["implemented_by"]:
                    status = f"implemented by {', '.join('#' + str(n) for n in h['implemented_by'])}"
                elif nxt and nxt["origin"] == "ticket":
                    shipped = f", shipped in {', '.join('#' + str(n) for n in nxt['implemented_by'])}" if nxt["implemented_by"] else ", not shipped yet"
                    status = f"written into {h['ticket']} ({nxt['requirement'].split(':')[-1]}){shipped}"
                elif nxt:
                    status = "replaced by a later chat change"
                else:
                    status = "never written into the ticket, not implemented"
                lines.append(f"{h['at'][:10]}: chat change on {h['ticket']}: \"{h['text']}\" ({status}).")
        if drift:
            for d in drift:
                stale = ", ".join(f"#{p['pr']}" for p in d["stale_prs"] if p["pr"] is not None) or "none"
                lines.append(f"DRIFT on {d['feature_name']}: {d['changed_by']} decided \"{d['requirement_text']}\" on "
                             f"{d['changed_at'][:10]} ({d['source']} #{d['channel']}), but {d['ticket']} still says "
                             f"\"{d['ticket_text']}\". PRs that shipped the old version: {stale}.")
        elif feature:
            lines.append(f"No open drift on {feature['name']}: its tickets and PRs match the latest decision.")
        else:
            lines.append("No open drift.")

    else:
        rows = run("list_features")
        drift = run("drift_for_feature")
        lines.append("Features: " + ", ".join(f"{r['name']} ({', '.join(r['tickets'])})" for r in rows) + ".")
        lines.append(f"Open drift: {len(drift)}" + (": " + ", ".join(d["feature_name"] for d in drift) if drift else "") + ".")

    if not lines:
        lines.append("I couldn't match that to a feature, person or ticket in the graph.")
    answer = "\n".join(lines)
    if paths:
        answer += "\n\nEvidence:\n" + "\n".join(paths[:3])
    return {"answer": answer, "tool_calls": calls, "paths": paths, "engine": "rules"}
