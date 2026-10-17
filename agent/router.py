"""Rules-based graph agent: answers questions from graph tools without an LLM.

Same response shape as agent.agent.ask(), so the API, the bots and the dashboard work with or without an
LLM. Routing is explicit and testable:

  entities  feature (TF-IDF over feature names + ticket titles, or a BD-id), person, PR-n / #n, BD-n
  intent    every intent is scored by weighted keyword matches; the best score wins, ties go to PRIORITY.
            blocked · projects · connect · who · impact · drift · decided · history · prs · overview
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
    "delay": [(r"\bdelay", 5), (r"\bslip(s|ped|ping)?\b", 5), (r"\bpush(ed)? (it |this )?(back|out)\b", 5), (r"\bpostpone", 5)],
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
    "plan": [
        (r"\bwhat needs to (happen|change)\b", 4),
        (r"\bhow (do|should|can) we fix\b", 4),
        (r"\bwho (needs|has) to\b", 4),
        (r"\bfix plan\b", 4),
        (r"\bplan\b", 2),
    ],
    "tasks": [(r"\bfollow-?ups?\b", 4), (r"\b(open )?tasks?\b", 3), (r"\bto-?dos?\b", 3)],
    # "why is the database migration delayed and who can approve an override?": chat -> doc -> ticket -> HR
    "blocked": [
        (r"\bwhy\b[^?]*\b(delayed|late|blocked|stuck|on hold|held up|waiting)\b", 8),
        (r"\boverride\b", 4),
        (r"\bwho can (approve|unblock|sign off)\b", 4),
        (r"\bunblock", 4),
        (r"\bblocker", 3),
    ],
    "projects": [
        (r"\b(active|current|ongoing|running|live|open)\b[^?]*\bprojects\b", 6),
        (r"\bprojects?\b[^?]*\b(active|running|on hold|paused|cancell?ed)\b", 6),
        (r"\b(which|what|list)\b[^?]*\bprojects\b", 3),
    ],
}
PRIORITY = [
    "blocked",
    "delay",
    "plan",
    "tasks",
    "projects",
    "drift",
    "decided",
    "impact",
    "connect",
    "who",
    "history",
    "prs",
    "overview",
]  # tie-break, first wins
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
        import time

        t0 = time.perf_counter()
        out = tools.call(name, args)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        self.calls.append({"tool": name, "args": args, "rows": len(out["rows"]), "ms": ms})
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
    if not rows:
        return [f"No causal path within 7 hops between {ids[0]} and {ids[1]}."]
    # the path is the answer: who posted what, which thread, which ticket, which PR
    return [f"{ids[0]} and {ids[1]} are {rows[0]['hops']} hops apart:", ctx.paths[-1] if ctx.paths else ""]


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
    o = ctx.run("ticket_owners", ticket=tid)
    if o and (o[0]["creator"] or o[0]["assignee"]):
        who = [f"{o[0]['creator_name']} (created it)" if o[0]["creator"] else None, f"{o[0]['assignee_name']} (assigned)" if o[0]["assignee"] else None]
        lines.append(f"{tid} is owned by " + " and ".join(w for w in who if w) + ".")
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


NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10}
DELAY = re.compile(r"\b(\d+|an?|one|two|three|four|five|six|seven|eight|ten)\s*(day|week|month)s?\b", re.I)


def delay_days(q: str) -> int:
    """'two weeks' -> 14, '3 days' -> 3, 'a month' -> 30; 14 when the question gives no amount."""
    m = DELAY.search(q)
    if not m:
        return 14
    n = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1).lower()]
    return n * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]


def answer_delay(ctx: Ctx) -> list[str]:
    from pipeline.impact import projects

    low = ctx.question.lower()
    target = (
        next((p["id"] for p in projects(ctx.g) if (p["name"] or "").lower() in low or re.search(rf"\b{re.escape(p['id'].lower())}\b", low)), None)
        or (ctx.feature["id"] if ctx.feature else None)
        or next((e for e in ctx.ents if not e.startswith("PR-")), None)
    )
    if not target:
        return unmatched(ctx, "a project, feature or ticket")
    rows = ctx.run("impact_of_delay", target=target, days=delay_days(ctx.question))
    if not rows:
        return unmatched(ctx, "a project, feature or ticket")
    r = rows[0]
    root = next(p for p in r["projects"] if p["root"]) if any(p["root"] for p in r["projects"]) else None
    lines = [
        f"If {r['target']['name']} slips {r['days']} days, its launch moves from {root['launch']} to {root['new_launch']}."
        if root
        else f"If {r['target']['name']} slips {r['days']} days:"
    ]
    for p in r["projects"]:
        if not p["root"] and p["via"]:
            effect = (
                f"slips {p['slip_days']} days (launch {p['launch']} → {p['new_launch']})"
                if p["slip_days"]
                else f"keeps its launch ({p['launch']}) but waits on it"
            )
            lines.append(f"Downstream: {p['name']} {effect}: {p['via']['from']} blocks {p['via']['to']} ({p['via']['why']}).")
    hit = [d for d in r["deliverables"] if d["moved"]]
    if hit:
        lines.append("Client deliverables:")
        for d in hit:
            state = f"misses its due date by {-d['slack_days']} days" if d["status"] == "misses" else f"{d['status']}, {d['slack_days']} days left"
            lines.append(f"- {d['client_name']}: {d['title']}, due {d['due']}, ready {d['ready']}: {state} (owner {d['owner']}).")
    else:
        lines.append("No client deliverable depends on it.")
    teams = [f"{t['name']} ({'; '.join(p['name'] + ': ' + ', '.join(p['roles'][:3]) for p in t['people'])})" for t in r["teams"]]
    lines.append(f"Teams affected ({len(teams)}): " + " · ".join(teams) + ".")
    for d in r["drift"]:
        lines.append(
            f"Also open: {d['ticket']} has a chat decision by {d['by']} that the ticket doesn't carry yet (“{d['text'][:90]}”). Worth folding into the new plan."
        )
    return lines


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


def answer_plan(ctx: Ctx) -> list[str]:
    """What has to change to close a drift and who owns each part (pipeline.work.plan, read-only)."""
    tickets = [e for e in ctx.ents if not e.startswith("PR-")]
    if not tickets:
        drift = ctx.run("drift_for_feature", **({"feature": ctx.feature["id"]} if ctx.feature else {}))
        tickets = [d["ticket"] for d in drift][:1]
    if not tickets:
        return [f"No open drift on {ctx.feature['name']}, so nothing to fix." if ctx.feature else "No open drift, so nothing to fix."]
    rows = ctx.run("plan_fix", ticket=tickets[0])
    if not rows:
        return [f"No open drift on {tickets[0]}, so nothing to fix."]
    items = [r for r in rows if r.get("kind") != "tell"]
    tell = next((r["people"] for r in rows if r.get("kind") == "tell"), [])
    lines = [f"To close the drift on {tickets[0]} ({items[0]['decided_by']}'s decision):"]
    for n, i in enumerate(items, 1):
        who = "" if i["kind"] == "ticket" else f" → {i['assignee'] or 'unassigned'}"
        lines.append(f"{n}. {i['what']}{who} ({i['why']})")
    if tell:
        lines.append("Also tell: " + ", ".join(tell) + ".")
    lines.append(f"Who can approve: {', '.join(items[0]['can_approve'])}. In Slack, reply `fix it` in the alert thread.")
    return lines


def answer_tasks(ctx: Ctx) -> list[str]:
    who = person_in(ctx.question, ctx.people)
    rows = ctx.run("follow_ups", **({"person": who[0]} if who else {}))
    if not rows:
        return [f"No open follow-ups for {who[0]}." if who else "No open follow-ups."]
    return [f"T-{r['num']}: {r['title']} → {r['assignee']} ({r['why']}; approved by {r['approved_by']})." for r in rows]


def _day(iso: str | None) -> str:
    """'2026-10-16' -> 'Fri 16 Oct'."""
    from datetime import date

    try:
        return date.fromisoformat((iso or "")[:10]).strftime("%a %d %b").replace(" 0", " ")
    except ValueError:
        return iso or "?"


def answer_blocked(ctx: Ctx) -> list[str]:
    rows = ctx.run("why_blocked", topic=ctx.question)
    if not rows:
        return ["I couldn't find delayed or blocked work matching that in the graph."]
    r = rows[0]
    first = (r["assignee_name"] or r["assignee"] or "").split(" ")[0]
    reason = r["reason"] or "no reason is written on the ticket"
    lines = [f"{r['ticket']} ({r['title']}) is {(r['state'] or 'open').lower()}: {reason[0].lower() + reason[1:]}."]
    o = r["out_of_office"]
    if o:
        lines.append(f"HR: {r['assignee_name']}, its assignee, is out of office ({o['kind'] or 'time off'}) from {_day(o['from'])} until {_day(o['until'])}.")
    if r["manager"]:
        also = ", who also opened the ticket" if r["creator"] == r["manager"] else ""
        lines.append(f"Who can approve an override: {r['manager_name']} ({r['manager_title']}), {first}'s manager{also}.")
    elif r["creator"]:
        lines.append(f"Who can approve an override: {r['creator']}, who opened the ticket.")
    hops = []
    if r["messages"]:
        m = r["messages"][0]
        hops.append(f"{m['author']}'s message in {(m['source'] or 'chat').capitalize()} #{m['channel']} ({_day(m['ts'])})")
    for d in r["docs"][:1]:
        hops.append(f"{(d['source'] or 'the').capitalize()} doc {d['id']} “{d['title']}”" if d["source"] else f"doc {d['id']} “{d['title']}”")
    hops.append(f"ticket {r['ticket']}")
    if r["assignee"]:
        hops.append(f"its assignee {r['assignee']}")
    if r["manager"]:
        hops.append(f"HR: {r['assignee']} reports to {r['manager']}")
    lines.append("Found by following: " + " → ".join(hops) + ".")
    return lines


def answer_projects(ctx: Ctx) -> list[str]:
    rows = ctx.run("list_projects")
    if not rows:
        return ["There are no projects in the graph."]
    active = [r for r in rows if r["status"] == "active"]
    lines = [f"{len(active)} active project{'' if len(active) == 1 else 's'}:"]
    for r in active:
        lines.append(f"- {r['name']} ({r['about']}): launch {r['launch']}, owner {r['owner']}, tickets {', '.join(r['tickets']) or 'none'}.")
    for r in rows:
        if r["status"] != "active":
            said = f" in {r['status_where']}: “{(r['status_text'] or '')[:140]}”" if r["status_text"] else ""
            lines.append(f"Not active: {r['name']} is {r['status']} ({r['status_by']}, {_day(r['status_at'])}{said}).")
    return lines


HANDLERS = {
    "blocked": answer_blocked,
    "projects": answer_projects,
    "plan": answer_plan,
    "tasks": answer_tasks,
    "connect": answer_connect,
    "prs": answer_prs,
    "who": answer_who,
    "impact": answer_impact,
    "delay": answer_delay,
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


KNOWLEDGE_MIN_SIM = 0.05  # cosine similarity for a passage to count (plus knowledge.search's shared-word check); set on 12 hand-written questions
SENSITIVE = re.compile(r"\b(salar(y|ies)|compensation|pay(roll)?|bonus(es)?|wages?|ssn|home address|medical|performance review)\b", re.I)


def _sensitive(q: str) -> bool:
    return bool(SENSITIVE.search(q))


def ask(question: str) -> dict:
    g = get_graph()
    feats, people = _features(g), _people(g)
    feature, sim = feature_match(question, feats)
    ctx = Ctx(g, question, feature, people, ids_in(g, question))
    gone = missing(g, ctx.ents)
    if gone:  # an id the graph doesn't have: say so instead of answering about something else
        return {"answer": f"I couldn't find {', '.join(gone)} in the graph.", "tool_calls": [], "paths": [], "engine": "rules", "intent": "unmatched"}
    intent = route(question, ctx.feature, ctx.ents)
    if intent == "unmatched":
        before = len(ctx.paths)
        hits = [h for h in ctx.run("search_knowledge", query=question) if h["similarity"] >= KNOWLEDGE_MIN_SIM]
        used = {h["chunk"] for h in hits[:3]}
        ctx.paths[before:] = [p for p in ctx.paths[before:] if any(f"Chunk {c})" in p for c in used)]  # evidence = passages used
        if hits:
            intent = "knowledge"
            lines = [f"From {hits[0]['title']} ({hits[0]['doc']}, by {hits[0]['author']}):", hits[0]["text"][:600]] + [
                f"Also: {h['title']} ({h['doc']})" for h in hits[1:3] if h["doc"] != hits[0]["doc"]
            ]
        else:
            lines = ["I don't have information on that you can access."] if ctx.ents == [] and _sensitive(question) else unmatched(ctx)
    else:
        lines = HANDLERS[intent](ctx)
    if feature and sim < ROUTER_FEATURE_WEAK_SIM and intent not in ("unmatched", "delay", "blocked", "projects"):  # these name their target
        lines = [f"(Low-confidence match: I read this as being about {feature['name']}.)"] + lines
    answer = "\n".join(lines)
    if ctx.paths:
        answer += "\n\nEvidence:\n" + "\n".join(ctx.paths[:3])
    return {"answer": answer, "tool_calls": ctx.calls, "paths": ctx.paths, "engine": "rules", "intent": intent}
