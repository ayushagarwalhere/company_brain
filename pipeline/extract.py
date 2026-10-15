"""Extraction: the judgments that need language understanding.

Two interchangeable extractors:
  * DeepSeekExtractor: the real one, LLM calls with JSON output.
  * OracleExtractor:   reads the answer key. Test harness only: it lets resolution
                       and drift logic be tested in isolation. Never used for
                       reported scores.

Both answer the same four questions:
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

CLASSIFY_SYSTEM = """You analyse messages from a software team's Slack/Discord to track product requirements.
Classify the TARGET message (use the thread only as context). Kinds:
- "decision": someone with authority states an agreed change to what a feature must do (scope, behaviour, limits, channel, defaults, placement...).
- "requirement_change": the message itself announces the requirement now differs from before, even without the word "decision".
- "request": a customer/teammate asks for or suggests something that has NOT been agreed yet.
- "rejected_proposal": a suggestion that is declined or parked.
- "reaffirmation": confirms the existing requirement stays as is.
- "status": progress update, PR announcements, review, done/merged.
- "question": a question without a change.
- "other": small talk or unrelated.
Only "decision" or "requirement_change" change requirements. A request is not a change until someone agrees to it.
If it is a change, write `requirement` as one self-contained sentence describing the NEW required behaviour (include concrete numbers).
`feature` must be one of the given feature ids or null. `ticket` is the ticket id the change modifies, or null if unclear.
Return JSON: {"kind": str, "feature": str|null, "ticket": str|null, "requirement": str|null, "confidence": 0..1}"""

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


class DeepSeekExtractor:
    name = "deepseek"

    def group_tickets(self, tickets: list[dict]) -> list[dict]:
        lines = "\n".join(f"{t['id']}: {t['title']} - {t['description']}" for t in tickets)
        out = llm.chat_json(GROUP_SYSTEM, lines)
        return [{"id": slug(f["name"]), "name": f["name"], "tickets": f["tickets"]} for f in out.get("features", [])]

    def classify(self, items: list[dict], features: list[dict]) -> dict[str, dict]:
        """items: [{"id", "author", "ts", "text", "thread": [{"author","text"}]}]"""
        feat_txt = "\n".join(f"- {f['id']} ({f['name']}): tickets " + ", ".join(
            f"{t['id']} \"{t['title']}\" = {t['description']}" for t in f["ticket_objs"]) for f in features)

        def one(it):
            thread = "\n".join(f"  {m['author']}: {m['text']}" for m in it["thread"]) or "  (none)"
            user = (f"Features:\n{feat_txt}\n\nThread context:\n{thread}\n\n"
                    f"TARGET message by {it['author']} at {it['ts']}:\n{it['text']}")
            try:
                return it["id"], llm.chat_json(CLASSIFY_SYSTEM, user)
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
        user = (f"Chat change ({chat_req['at']}): {chat_req['text']}\n\n"
                f"Ticket text after edit ({ticket_req['at']}): {ticket_req['text']}")
        return bool(llm.chat_json(REFLECTS_SYSTEM, user).get("reflects"))

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
                out[mid] = {"kind": "decision", "feature": r["feature"], "ticket": self._ticket_for(r),
                            "requirement": r["text"], "confidence": 1.0}
            elif mid in non:
                out[mid] = {"kind": non[mid]["kind"], "feature": non[mid]["feature"], "ticket": None,
                            "requirement": None, "confidence": 1.0}
            else:
                out[mid] = {"kind": "other", "feature": feat_of.get(mid), "ticket": None,
                            "requirement": None, "confidence": 1.0}
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


    def reflects(self, ticket_req, chat_req):
        from pipeline.events import to_ms
        msg = chat_req["id"].removeprefix("req:")
        dec = next((d for d in self.key["decisions"] if d["message"] == msg), None)
        r = self.reqs.get(dec["changes"]) if dec else None
        seen = (r or {}).get("reflected_in_ticket")
        return bool(seen) and ticket_req["at_ms"] >= to_ms(seen["at"])

def get_extractor(name: str):
    return {"deepseek": DeepSeekExtractor, "oracle": OracleExtractor}[name]()
