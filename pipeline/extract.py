"""Extraction: the judgments that need language understanding.

Three interchangeable extractors:
  * LLMExtractor:       the real one, LLM calls with structured JSON output (DeepSeek, or local via Ollama).
  * HeuristicExtractor: rules only (labels, decision phrasing, text diffs). No LLM, no
                        answer key: the honest fallback and the baseline for the LLM.
  * OracleExtractor:   reads the answer key. Test harness only: it lets resolution
                       and drift logic be tested in isolation. Never used for
                       reported scores.

All answer the same four questions:
  1. group_tickets:  which tickets belong to the same product feature?
  2. classify:       does this chat message change a requirement? to what?
  3. implements:     which requirement versions does this PR actually implement?
  4. reflects:       does a later ticket edit actually contain an earlier chat change?
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline import llm

KEY_PATH = Path(__file__).resolve().parent.parent / "data" / "scenario" / "answer_key.json"

CHANGE_KINDS = {"decision", "requirement_change"}

CLASSIFY_SYSTEM = """You decide whether ONE chat message (the TARGET) changes a product requirement. Use the thread only as context.

A requirement change says that what a feature must do is now different (scope, behaviour, limits, channel, defaults,
placement, numbers), stated as an agreed decision or an announced change by someone deciding it.

These are NOT changes (is_change = false), even when they contain words like "decision", "agreed", "instead of" or "let's":
- code review remarks and replies to review about how the code is written (naming, refactors, tests, helpers)
- status updates: a PR is opened, merged, deployed, rebased or blocked; "fixed by #n"; tests are green
- analysis, bug reports and reproductions, including ones that say a decision is NEEDED or list options
- offers to do work and plans that nobody has agreed to ("I'd like to pick this up", "I'll change X to Y", "what if we...?", "idea:")
- requests from customers or teammates that nobody has agreed to
- questions, rejections ("not this quarter", "let's not") and reaffirmations ("keep it as is")

Return JSON:
{"is_change": true|false,
 "kind": "decision"|"requirement_change"|"request"|"proposal"|"status"|"review"|"analysis"|"question"|"rejected_proposal"|"reaffirmation"|"other",
 "old": what the requirement was before, or null,
 "new": if is_change, ONE self-contained sentence with the NEW required behaviour (concrete numbers), else null,
 "evidence_quote": if is_change, the exact words copied from the TARGET message that state the change, else null,
 "feature": one of the given feature ids, or null,
 "ticket": the ticket id the change modifies, or null,
 "confidence": 0..1}"""

REPLACES_SYSTEM = """Two chat messages each changed the requirement of the same ticket. Decide whether the LATER one revises,
reverses or replaces the EARLIER decision (the same aspect of the feature), rather than being about something else
or being only a status update, proposal or remark.
Return JSON: {"replaces": true|false, "reason": short explanation}"""


def _norm(text: str | None) -> str:
    """Lower-case, one space between words, and no line-leading comment or quote markers (`//`, `#`, `>`, `*`, `--`):
    a model quoting a sentence from a code comment or a quoted reply drops those markers. Found on golang/go#77441,
    where an accepted API change sat in a `//` doc comment and the guard threw the (correct) extraction away."""
    text = re.sub(r"(?m)^[ \t]*(?://+|#+|>+|\*+|--)[ \t]?", "", text or "")
    return re.sub(r"\s+", " ", text.lower().replace("\u2019", "'")).strip(" .\"'`*")


def evidence_ok(quote: str | None, message: str) -> bool:
    """The model must copy the words that state the change; a quote that isn't in the message means
    the change was made up, so the extraction is discarded (cheap guard against hallucinated changes)."""
    q = _norm(quote)
    return len(q) >= 8 and q in _norm(message)


def _confidence(v) -> float:
    """Models don't always respect the schema: gpt-oss-20b sometimes returns "0.8" as a string. Anything unparseable
    counts as 0.0, which is below MIN_CONFIDENCE, so it can never become a change."""
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def from_structured(out: dict, message: str) -> dict:
    """Maps the structured answer to the pipeline's {kind, feature, ticket, requirement, confidence}."""
    base = {
        "feature": out.get("feature"),
        "ticket": out.get("ticket"),
        "confidence": _confidence(out.get("confidence")),
        "evidence_quote": out.get("evidence_quote"),
        "old": out.get("old"),
    }
    if not out.get("is_change") or not out.get("new"):
        return {**base, "kind": out.get("kind") if out.get("kind") not in CHANGE_KINDS else "other", "requirement": None}
    if not evidence_ok(out.get("evidence_quote"), message):
        return {**base, "kind": "other", "requirement": None, "guard": "evidence_not_in_message"}
    return {**base, "kind": "decision" if out.get("kind") == "decision" else "requirement_change", "requirement": out["new"]}


GROUP_SYSTEM = """Group a startup's tickets into product features. A feature is a user-facing capability that several tickets may contribute to
(backend, frontend, tests, follow-ups). Tickets that are unrelated one-offs (chores, typo fixes, unrelated bugs) go in their own feature
only if they are user-facing capabilities; otherwise leave them out.
Return JSON: {"features": [{"name": short feature name, "tickets": [ticket ids]}]}. Each ticket appears at most once."""

IMPLEMENTS_SYSTEM = """You check whether a pull request implements specific requirement versions.
For each candidate requirement, decide if the PR's described behaviour satisfies it fully. A PR that implements an OLDER behaviour
(e.g. a different time window, channel or columns) does NOT implement a newer requirement that changed that behaviour.
Return JSON: {"implements": [requirement ids fully implemented], "reason": short explanation}"""


REFLECTS_SYSTEM = """A requirement was changed in chat. Later the ticket text was edited.
Decide whether the NEW ticket text incorporates the chat change (same behaviour, numbers, scope), even if worded differently.
An edit that leaves the old behaviour in place does NOT reflect it.
Return JSON: {"reflects": true|false, "reason": short explanation}"""


def slug(name: str) -> str:
    return "feat_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


class LLMExtractor:
    """Any OpenAI-compatible model (pipeline/llm.py): DeepSeek, or a local one through Ollama."""

    name = "llm"

    def group_tickets(self, tickets: list[dict]) -> list[dict]:
        lines = "\n".join(f"{t['id']}: {t['title']} - {t['description']}" for t in tickets)
        out = llm.chat_json(GROUP_SYSTEM, lines)
        # a model sometimes returns a group without its ticket list (seen on a real repo's 65 issues): skip what's malformed
        return [
            {"id": slug(f["name"]), "name": f["name"], "tickets": [t for t in f.get("tickets") or [] if isinstance(t, str)]}
            for f in out.get("features", [])
            if isinstance(f, dict) and f.get("name")
        ]

    def classify(self, items: list[dict], features: list[dict]) -> dict[str, dict]:
        """items: [{"id", "author", "ts", "text", "thread": [{"author","text"}]}]"""
        feat_txt = "\n".join(
            f"- {f['id']} ({f['name']}): tickets " + ", ".join(f"{t['id']} \"{t['title']}\" = {t['description']}" for t in f["ticket_objs"]) for f in features
        )

        def one(it):
            thread = "\n".join(f"  {m['author']}: {m['text']}" for m in it["thread"]) or "  (none)"
            user = f"Features:\n{feat_txt}\n\nThread context:\n{thread}\n\n" f"TARGET message by {it['author']} at {it['ts']}:\n{it['text']}"
            try:
                return it["id"], from_structured(llm.chat_json(CLASSIFY_SYSTEM, user), it["text"])
            except Exception as e:  # noqa: BLE001 - one bad call shouldn't kill the run
                return it["id"], {"kind": "error", "error": str(e)}

        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(pool.map(one, items))

    def implements(self, pr: dict, candidates: list[dict]) -> list[str]:
        cand = "\n".join(f"{c['id']} ({c['at']}): {c['text']}" for c in candidates)
        user = f"PR #{pr['number']}: {pr['title']}\n{pr['body']}\n\nCandidate requirements:\n{cand}"
        ids = {c["id"] for c in candidates}
        return [i for i in llm.chat_json(IMPLEMENTS_SYSTEM, user).get("implements", []) if i in ids]

    def reflects(self, ticket_req: dict, chat_req: dict) -> bool:
        user = f"Chat change ({chat_req['at']}): {chat_req['text']}\n\n" f"Ticket text after edit ({ticket_req['at']}): {ticket_req['text']}"
        return bool(llm.chat_json(REFLECTS_SYSTEM, user).get("reflects"))

    def replaces(self, new_req: dict, old_req: dict) -> bool:
        user = f"EARLIER ({old_req['at']}): {old_req['text']}\n\nLATER ({new_req['at']}): {new_req['text']}"
        return bool(llm.chat_json(REPLACES_SYSTEM, user).get("replaces"))


class OracleExtractor:
    """Answer-key extractor (test harness only)."""

    name = "oracle"

    def __init__(self):
        self.key = json.loads(KEY_PATH.read_text(encoding="utf-8"))
        self.reqs = {r["id"]: r for r in self.key["requirements"]}

    def group_tickets(self, tickets):
        return [{"id": f["id"], "name": f["name"], "tickets": f["tickets"]} for f in self.key["features"]]

    def _ticket_for(self, req):
        if req.get("reflected_in_ticket"):
            return req["reflected_in_ticket"]["id"]
        for d in self.key["expected_drift"]:
            if d["requirement"] == req["id"]:
                return d["ticket"]
        return None

    def classify(self, items, features):
        out = {}
        decisions = {d["message"]: d for d in self.key["decisions"]}
        non = {n["message"]: n for n in self.key["non_changes"]}
        feat_of = {m: f for f, ms in self.key["message_links"].items() for m in ms}
        for it in items:
            mid = it["id"]
            if mid in decisions:
                r = self.reqs[decisions[mid]["changes"]]
                out[mid] = {"kind": "decision", "feature": r["feature"], "ticket": self._ticket_for(r), "requirement": r["text"], "confidence": 1.0}
            elif mid in non:
                out[mid] = {"kind": non[mid]["kind"], "feature": non[mid]["feature"], "ticket": None, "requirement": None, "confidence": 1.0}
            else:
                out[mid] = {"kind": "other", "feature": feat_of.get(mid), "ticket": None, "requirement": None, "confidence": 1.0}
        return out

    def implements(self, pr, candidates):
        link = next((p for p in self.key["pr_links"] if p["pr"] == pr["number"]), None)
        if not link or not link.get("implements"):
            return []
        r = self.reqs[link["implements"]]
        anchor = r.get("reflected_in_ticket") or r["origin"]
        # The graph's node for this requirement is the ticket version written at that time
        from pipeline.events import to_ms

        at = to_ms(anchor["at"])
        return [c["id"] for c in candidates if c["at_ms"] == at]

    def replaces(self, new_req, old_req):
        def key_req(r):
            dec = next((d for d in self.key["decisions"] if d["message"] == r["id"].removeprefix("req:")), None)
            return dec["changes"] if dec else None

        new = self.reqs.get(key_req(new_req) or "")
        return bool(new) and new.get("supersedes") == key_req(old_req)

    def reflects(self, ticket_req, chat_req):
        from pipeline.events import to_ms

        msg = chat_req["id"].removeprefix("req:")
        dec = next((d for d in self.key["decisions"] if d["message"] == msg), None)
        r = self.reqs.get(dec["changes"]) if dec else None
        seen = (r or {}).get("reflected_in_ticket")
        return bool(seen) and ticket_req["at_ms"] >= to_ms(seen["at"])


class HeuristicExtractor:
    """Rule-based extractor: no LLM, no answer key. Every rule is explainable, which makes
    it the honest fallback when no DeepSeek key is configured, and a baseline for the LLM."""

    name = "heuristic"
    replaces = None  # rules can't judge whether one decision revises another: chat never supersedes chat

    GENERIC_LABELS = {"backend", "frontend", "bug", "tests", "tech-debt", "docs", "security", "performance", "notifications", "reporting", "profile", "search"}
    DECISION = re.compile(
        r"\bdecision\b|\blet'?s (change|add|do|make|switch|drop|move|use)\b|\bagreed\b|"
        r"\bwe('ll| will) (now )?(do|send|support|use|switch|drop)\b|\binstead of\b|"
        r"\bmust (now )?(support|include|be)\b|\bfrom now on\b|\bchange of plan\b",
        re.I,
    )
    REJECT = re.compile(r"not this quarter|\bpark\b|let'?s not|\bno, keep\b|\bkeep it as is\b|\bwon'?t do\b", re.I)
    LEAD = re.compile(r"^(decision( after [^:]*)?:|agreed\.?|good call\.?)\s*", re.I)
    NUM = re.compile(r"\d+")

    def group_tickets(self, tickets):
        from pipeline.textsim import tokens

        topic = {}
        for t in tickets:
            labels = [l for l in t.get("labels") or [] if l not in self.GENERIC_LABELS]
            if labels:
                topic[t["id"]] = labels[0]
        counts = {}
        for lab in topic.values():
            counts[lab] = counts.get(lab, 0) + 1
        groups = {lab: [] for lab, c in counts.items() if c >= 2}
        for t in tickets:
            lab = topic.get(t["id"])
            if lab in groups:
                groups[lab].append(t)
                continue
            # no topic label: join the feature whose label appears in the ticket's own text
            words = set(tokens(f"{t['title']} {t['description']}"))
            hit = next((g for g in groups if g in words), None)
            if hit:
                groups[hit].append(t)
        out = []
        for ts in groups.values():
            first = min(ts, key=lambda x: x["id"])
            out.append({"id": slug(first["title"]), "name": first["title"], "tickets": [x["id"] for x in ts]})
        return out

    def classify(self, items, features):
        from pipeline.textsim import tokens

        out = {}
        for it in items:
            text = it["text"].strip()
            sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
            # the sentence carrying the decision must be a statement, not a question
            hit = next((x for x in sentences if self.DECISION.search(x)), None)
            is_change = hit is not None and not hit.endswith("?") and not self.REJECT.search(text) and len(tokens(text)) >= 6
            req = None
            if is_change:
                kept = [self.LEAD.sub("", x) for x in sentences if not x.endswith("?")]
                req = " ".join(x for x in kept if len(tokens(x)) >= 3) or self.LEAD.sub("", text)
            out[it["id"]] = {
                "kind": "decision" if is_change else "other",
                "feature": None,
                "ticket": None,
                "requirement": req,
                "confidence": 0.7 if is_change else 0.0,
            }
        return out

    def implements(self, pr, candidates):
        from pipeline.events import TICKET_REF
        from pipeline.textsim import TfIdf

        nums = lambda s: set(self.NUM.findall(TICKET_REF.sub("", s)))  # noqa: E731 - ticket ids aren't requirements
        text = f"{pr['title']} {pr['body']}"
        # a requirement whose numbers (30 days, 12 months, 15 minutes) aren't in the PR isn't what it implements
        ok = [c for c in candidates if nums(c["text"]) <= nums(text)]
        if not ok:
            return []
        best, score = TfIdf({c["id"]: c["text"] for c in ok}).best(text)
        return [best] if best and score >= 0.2 else []

    EDIT_NOISE = {
        "typo",
        "fix",
        "fixed",
        "fixes",
        "wording",
        "reword",
        "reworded",
        "clarify",
        "clarified",
        "format",
        "formatting",
        "minor",
        "cleanup",
        "update",
        "updated",
        "updating",
        "edit",
        "edited",
        "note",
    }

    def reflects(self, ticket_req, chat_req):
        """A ticket edit reflects a chat change if the words it ADDED carry that change's content:
        at least one shared content word (edit chatter like "typo fixed" doesn't count), and, when the
        change states numbers (12 months, 15 minutes), at least one of those numbers."""
        from pipeline.events import TICKET_REF
        from pipeline.textsim import tokens

        added = set(tokens(ticket_req["text"])) - set(tokens(ticket_req.get("prev_text") or ""))
        chat_text = TICKET_REF.sub("", chat_req["text"])
        content = set(tokens(chat_text)) - self.EDIT_NOISE
        if not added & content:
            return False
        nums = set(self.NUM.findall(chat_text))
        return not nums or bool(nums & added)


def get_extractor(name: str):
    # "deepseek" is the old name of the LLM extractor, kept so existing commands work
    return {"llm": LLMExtractor, "deepseek": LLMExtractor, "oracle": OracleExtractor, "heuristic": HeuristicExtractor}[name]()
