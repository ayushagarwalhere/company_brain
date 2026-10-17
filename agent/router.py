"""Rules-based graph agent: answers questions from graph tools without an LLM.

Same response shape as agent.agent.ask(), so the API, the bots and the dashboard work with or without an
LLM. Routing is explicit and testable:

  entities  feature (TF-IDF over feature names + ticket titles, or a BD-id), person, PR-n / #n, BD-n
  intent    every intent is scored by weighted keyword matches; the best score wins, ties go to PRIORITY.
            connect · who · impact · drift · decided · history · prs · overview
  failure   a question that needs an entity it can't resolve gets an explicit "couldn't match" answer with
            examples that work, instead of falling through to an unrelated overview.
"""

import re
from dataclasses import dataclass, field

from agent import tools
from config import ROUTER_FEATURE_MIN_SIM, ROUTER_FEATURE_WEAK_SIM
from graph import queries as Q
from graph.db import get_graph
from pipeline.textsim import TfIdf, tokens

# (pattern, weight) per intent. Weights say how strongly a phrase signals the intent.
INTENT_RULES: dict[str, list[tuple[str, int]]] = {
    "connect": [(r"\bconnect(ed|ion)?\b", 3), (r"\blink(ed)? between\b", 3), (r"\bpath (from|between)\b", 3), (r"→", 3)],
    "who": [(r"^\s*who\b", 2), (r"\bwho\b", 2), (r"\bknows?\b", 1), (r"\bowns?\b", 1), (r"\bexpert", 2), (r"\bworked\b", 1), (r"\bask\b", 1)],
    "impact": [(r"\bimpact", 3), (r"\baffect(ed|s)?\b", 3)],
    "drift": [
        (r"\bdrift", 3),
        (r"\bdiverg", 2),
        (r"\bout of (sync|date)\b", 2),
        (r"\bstale\b", 2),
        (r"\bmismatch", 2),
        (r"\bstill accurate\b", 2),
        (r"\blater changed\b", 2),
        (r"\bchanged in chat\b", 2),
    ],
    "decided": [
        (r"\bwho decided\b", 3),
        (r"\bdecid", 2),
        (r"\bdecision", 2),
        (r"\bship(ped)?\b", 1),
        (r"\bimplement", 1),
        (r"\bmatch(es)?\b", 2),
        (r"\bcurrent requirement", 3),
        (r"\bagreed\b", 2),
        (r"\bfollow(ed)? the latest\b", 3),
    ],
    "history": [(r"\bhistory\b", 3), (r"\btimeline\b", 3), (r"\bevolv", 2), (r"\bchanged?\b", 1), (r"\bwritten back\b", 2)],
    "prs": [(r"\b(which|what) (pr|pull request)s?\b", 2), (r"\bpull requests?\b", 1), (r"\bPRs?\b", 1)],
    "overview": [(r"\boverview\b", 3), (r"\bsummar", 3), (r"\bwhat'?s (going on|new)\b", 3)],
}
PRIORITY = ["drift", "decided", "impact", "connect", "who", "history", "prs", "overview"]  # tie-break, first wins
# Tickets: any PROJECT-123 id (BD-101, SC-30). PRs: "PR-6", "PR 6", "PR6", "pull request 6", "#6".
TICKET_ID = re.compile(r"\b(?!PR-)([A-Z]{2,6}-\d+)\b", re.I)
PR_ID = re.compile(r"\b(?:PR|pull request)\s*[-#]?\s*(\d+)\b|#(\d+)\b", re.I)
EXAMPLES = ["Which features have drifted, and why?", "Who knows the most about ticket export?", "How is liam connected to PR-6?"]


def score_intents(question: str) -> dict[str, int]:
    return {name: sum(w for rx, w in rules if re.search(rx, question, re.I)) for name, rules in INTENT_RULES.items()}


def pick_intent(question: str) -> str | None:
    scores = score_intents(question)
    best = max(scores.values())
    if best == 0:
        return None
    return next(name for name in PRIORITY if scores[name] == best)


def entities(question: str) -> list[str]:
    """BD-101 -> 'BD-101'; PR-6, PR 6, pull request 6 and #6 -> 'PR-6'. In order of appearance."""
    found = [(m.start(), m.group(1).upper()) for m in TICKET_ID.finditer(question)]
    found += [(m.start(), f"PR-{m.group(1) or m.group(2)}") for m in PR_ID.finditer(question)]
    out: list[str] = []
    for _, e in sorted(found):
        if e not in out:
            out.append(e)
    return out


def missing(g, ents: list[str]) -> list[str]:
    """Named ticket / PR ids that aren't in the graph. A question about BD-999 must say so, not answer about
    something else."""
    if not ents:
        return []
    known = {r["id"] for r in Q.rows(g, "MATCH (n) WHERE (n:Ticket OR n:PullRequest) AND n.id IN $ids RETURN n.id AS id", ids=ents)}
    return [e for e in ents if e not in known]


def ids_in(g, question: str) -> list[str]:
    """entities(), keeping a PROJECT-123 token only when PROJECT is a ticket prefix this graph uses, so
    "GPT-4" or "UTF-8" in a question isn't treated as a missing ticket."""
    prefixes = {r["p"] for r in Q.rows(g, "MATCH (t:Ticket) RETURN DISTINCT split(t.id, '-')[0] AS p")}
    return [e for e in entities(question) if e.startswith("PR-") or e.split("-")[0] in prefixes]


def _features(g):
    return Q.rows(
        g,
        """MATCH (f:Feature) OPTIONAL MATCH (t:Ticket)-[:ABOUT]->(f)
                        RETURN f.id AS id, f.name AS name, collect(t.id) AS tickets, collect(t.title) AS titles""",
    )


def feature_match(q: str, feats: list[dict]) -> tuple[dict | None, float]:
    """(feature, similarity). A named ticket id is an exact match (1.0)."""
    named = {e for e in entities(q) if not e.startswith("PR-")}
    for f in feats:
        if named & set(f["tickets"]):
            return f, 1.0
    if not feats:
        return None, 0.0
    sim = TfIdf({f["id"]: f"{f['name']} {f['name']} {' '.join(f['titles'])}" for f in feats})
    best, score = sim.best(q)
    return (next((f for f in feats if f["id"] == best), None), score) if score >= ROUTER_FEATURE_MIN_SIM else (None, score)


def feature_for(q: str, feats: list[dict]) -> dict | None:
    return feature_match(q, feats)[0]


def _people(g):
    return Q.rows(g, "MATCH (p:Person) RETURN p.id AS id, p.name AS name")


def person_in(q: str, people: list[dict]) -> list[str]:
    words = set(tokens(q))
    return [p["id"] for p in people if p["id"] in words or (p["name"] or "").split(" ")[0].lower() in words]


@dataclass
class Ctx:
    g: object
    question: str
    feature: dict | None
    people: list[dict]
    ents: list[str]
    calls: list = field(default_factory=list)
    paths: list = field(default_factory=list)

    def run(self, name, **args):
        out = tools.call(name, args)
        self.calls.append({"tool": name, "args": args, "rows": len(out["rows"])})
        self.paths.extend(p for p in out["paths"] if p not in self.paths)
        return out["rows"]


def unmatched(ctx: Ctx, what: str = "a feature, person or ticket") -> list[str]:
    return [f"I couldn't match that to {what} in the graph. Questions like these work:"] + [f"- {e}" for e in EXAMPLES]


# ---------------------------------------------------------------- one function per intent


def answer_connect(ctx: Ctx) -> list[str]:
    ids = person_in(ctx.question, ctx.people) + ctx.ents
    if len(ids) < 2:
        return ['Name two things to connect, e.g. a person and a PR: "How is liam connected to PR-6?"']
    rows = ctx.run("how_connected", a=ids[0], b=ids[1])
    return [f"{ids[0]} and {ids[1]} are {rows[0]['hops']} hops apart." if rows else f"No causal path within 7 hops between {ids[0]} and {ids[1]}."]


def answer_prs(ctx: Ctx) -> list[str]:
    if not ctx.feature:
        return unmatched(ctx, "a feature")
    lines = []
    for r in ctx.run("feature_prs", feature=ctx.feature["id"]):
        how = "" if r["link"] == ["hard"] else f", linked by {', '.join(r['link'])} (the PR never names its ticket)"
        lines.append(f"PR #{r['pr']} \"{r['title']}\" by {r['author']} → {', '.join(r['tickets']) or 'no ticket'}{how}.")
    return lines or [f"No pull requests are linked to {ctx.feature['name']}."]


def answer_who(ctx: Ctx) -> list[str]:
    tickets = [e for e in ctx.ents if e.startswith("BD-")]
    prs = [e for e in ctx.ents if e.startswith("PR-")]
    if tickets:
        return answer_who_ticket(ctx, tickets[0])
    if prs:
        return answer_who_pr(ctx, prs[0])
    if ctx.feature:
        top = ctx.run("who_knows", feature=ctx.feature["id"])[:3]
        return [f"For {ctx.feature['name']}: " + "; ".join(f"{r['name']} ({r['role']}, {r['items']} items, score {int(r['score'])})" for r in top) + "."]
    return unmatched(ctx)


def answer_who_ticket(ctx: Ctx, tid: str) -> list[str]:
    lines = []
    owner = Q.rows(ctx.g, "MATCH (t:Ticket {id: $t})-[:ASSIGNED_TO]->(p:Person) RETURN p.name AS name, p.role AS role", t=tid)
    if owner:
        lines.append(f"{tid} is owned by {owner[0]['name']} ({owner[0]['role']}).")
    for d in ctx.run("drift_for_feature", **({"feature": ctx.feature["id"]} if ctx.feature else {})):
        if d["ticket"] == tid:
            stale = stale_pr_list(d)
            lines.append(
                f"Their shipped work ({stale}) is stale because of {d['changed_by']}'s decision on " f"{d['changed_at'][:10]}: \"{d['requirement_text']}\"."
            )
    return lines or [f"I couldn't find a ticket {tid} in the graph."]


def answer_who_pr(ctx: Ctx, pid: str) -> list[str]:
    rows = Q.rows(
        ctx.g,
        """MATCH (a:Person)-[:AUTHORED]->(pr:PullRequest {id: $pr}) OPTIONAL MATCH (pr)-[:REFERENCES]->(t:Ticket)
                            RETURN a.id AS author, pr.number AS n, pr.title AS title, collect(t.id) AS tickets""",
        pr=pid,
    )
    if not rows:
        return [f"I couldn't find {pid} in the graph."]
    r = rows[0]
    return [f"PR #{r['n']} \"{r['title']}\" was written by {r['author']}; it references {', '.join(r['tickets']) or 'no ticket'}."]


def answer_impact(ctx: Ctx) -> list[str]:
    if not ctx.feature:
        return unmatched(ctx, "a feature")
    decs = ctx.run("list_decisions", feature=ctx.feature["id"])
    if not decs:
        return [f"No decisions recorded in chat for {ctx.feature['name']}."]
    d = decs[-1]
    return [
        f"{d['by']}'s decision on {d['at'][:10]} (\"{d['text']}\") changes {r['ticket']} "
        f"(owner {r['owner']}); PRs on it: {', '.join('#' + str(n) for n in r['prs']) or 'none'}; "
        f"related tickets: {', '.join(r['related_tickets']) or 'none'}."
        for r in ctx.run("decision_impact", decision=d["id"])
    ]


def history_lines(ctx: Ctx) -> list[str]:
    seen, uniq = set(), []
    for h in ctx.run("decision_history", feature=ctx.feature["id"]):
        if h["requirement"] not in seen:  # a requirement changed by both a Message and its Decision appears twice
            seen.add(h["requirement"])
            uniq.append(h)
    by_super = {h["supersedes"]: h for h in uniq if h["supersedes"]}
    lines = []
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
    return lines


def stale_pr_list(d: dict) -> str:
    """'#5 (after the decision), #4': every stale PR (unmatched ones get their own line in drift_lines)."""
    return Q.pr_list({**d, "unmatched_prs": []})


def drift_lines(ctx: Ctx) -> list[str]:
    drift = ctx.run("drift_for_feature", **({"feature": ctx.feature["id"]} if ctx.feature else {}))
    tickets = [e for e in ctx.ents if not e.startswith("PR-")]
    if tickets:  # "is BD-102 up to date": answer about BD-102, not about its feature's other tickets
        drift = [d for d in drift if d["ticket"] in tickets]
        if not drift:
            return [f"No open drift on {', '.join(tickets)}: the ticket matches the latest decision."]
    lines = []
    for d in drift:
        # one fact per line, so the answer reads as a short list rather than a paragraph
        lines += [
            f"DRIFT on {d['feature_name']}.",
            f"Decided: \"{d['requirement_text']}\" ({d['changed_by']}, {d['changed_at'][:10]}, {d['source']} #{d['channel']}).",
            f"{d['ticket']} still says: \"{d['ticket_text']}\"",
            f"PRs that shipped the old version: {stale_pr_list(d)}.",
        ]
        if d.get("unmatched_prs"):
            lines.append(f"Unmatched, may implement the new scope: {', '.join('#' + str(p['pr']) for p in d['unmatched_prs'])}.")
        if d["stale_docs"]:
            lines.append(f"Docs still describing the old version: {', '.join(x['title'] for x in d['stale_docs'])}.")
    if not drift:
        lines.append(f"No open drift on {ctx.feature['name']}: its tickets and PRs match the latest decision." if ctx.feature else "No open drift.")
    return lines


def answer_drift(ctx: Ctx) -> list[str]:
    prs = [e for e in ctx.ents if e.startswith("PR-")]
    return pr_lines(ctx, prs) if prs else drift_lines(ctx)


def pr_lines(ctx: Ctx, prs: list[str]) -> list[str]:
    """For a named PR: is it on an open drift, and in which role (stale, or unmatched)."""
    drift = ctx.run("drift_for_feature", **({"feature": ctx.feature["id"]} if ctx.feature else {}))
    lines = []
    for pid in prs:
        n = int(pid.split("-")[1])
        hits = [(d, p) for d in drift for p in d["stale_prs"] + (d.get("unmatched_prs") or []) if p["pr"] == n]
        for d, p in hits:
            lines.append(
                f"PR #{n} {p['label']} on {d['ticket']} ({d['feature_name']}): {d['ticket']} still says \"{d['ticket_text']}\", "
                f"but {d['changed_by']} decided \"{d['requirement_text']}\" on {d['changed_at'][:10]}."
            )
        if not hits:
            lines.append(f"PR #{n} is not on any open drift: nothing newer was decided for what it shipped.")
    return lines


def answer_decided(ctx: Ctx) -> list[str]:
    """What was decided, whether it shipped, and which PR shipped what (history + drift with the shipping PRs)."""
    prs = [e for e in ctx.ents if e.startswith("PR-")]
    if prs:  # "did PR #6 ship the right thing?"
        return pr_lines(ctx, prs)
    tickets = [e for e in ctx.ents if not e.startswith("PR-")]
    if tickets:  # "is BD-102 up to date?": that ticket's text, its own chat changes, its own drift
        said = Q.rows(ctx.g, "MATCH (t:Ticket) WHERE t.id IN $ids RETURN t.id AS id, t.title AS title, t.description AS text", ids=tickets)
        own = [line for line in history_lines(ctx) if any(f"on {t}:" in line for t in tickets)] if ctx.feature else []
        return (
            [f"{r['id']} ({r['title']}) says: \"{r['text']}\"" for r in said] + (own or [f"No chat decision changed {', '.join(tickets)}."]) + drift_lines(ctx)
        )
    if not ctx.feature:
        return drift_lines(ctx)
    return history_lines(ctx) + drift_lines(ctx)


def answer_history(ctx: Ctx) -> list[str]:
    if not ctx.feature:
        return unmatched(ctx, "a feature")
    return history_lines(ctx) + drift_lines(ctx)


def answer_overview(ctx: Ctx) -> list[str]:
    rows = ctx.run("list_features")
    drift = ctx.run("drift_for_feature")
    return [
        "Features: " + ", ".join(f"{r['name']} ({', '.join(r['tickets'])})" for r in rows) + ".",
        f"Open drift: {len(drift)}" + (": " + ", ".join(d["feature_name"] for d in drift) if drift else "") + ".",
    ]


HANDLERS = {
    "connect": answer_connect,
    "prs": answer_prs,
    "who": answer_who,
    "impact": answer_impact,
    "drift": answer_drift,
    "decided": answer_decided,
    "history": answer_history,
    "overview": answer_overview,
}


def route(question: str, feature: dict | None, ents: list[str]) -> str:
    """Intent name, or 'unmatched'. A question with no intent keyword but a known feature gets the drift/decision view."""
    intent = pick_intent(question)
    if intent is None:
        return "decided" if feature else "unmatched"
    return intent


def ask(question: str) -> dict:
    g = get_graph()
    feats, people = _features(g), _people(g)
    feature, sim = feature_match(question, feats)
    ctx = Ctx(g, question, feature, people, ids_in(g, question))
    gone = missing(g, ctx.ents)
    if gone:  # an id the graph doesn't have: say so instead of answering about something else
        return {"answer": f"I couldn't find {', '.join(gone)} in the graph.", "tool_calls": [], "paths": [], "engine": "rules", "intent": "unmatched"}
    intent = route(question, ctx.feature, ctx.ents)
    lines = unmatched(ctx) if intent == "unmatched" else HANDLERS[intent](ctx)
    if feature and sim < ROUTER_FEATURE_WEAK_SIM and intent != "unmatched":
        lines = [f"(Low-confidence match: I read this as being about {feature['name']}.)"] + lines
    answer = "\n".join(lines)
    if ctx.paths:
        answer += "\n\nEvidence:\n" + "\n".join(ctx.paths[:3])
    return {"answer": answer, "tool_calls": ctx.calls, "paths": ctx.paths, "engine": "rules", "intent": intent}
