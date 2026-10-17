"""Pure-logic tests (no database, no API keys)."""

from benchmark.run import grade
from connectors.github import parse_body, trailer_block
from pipeline.events import find_ticket_refs, from_ms, to_ms
from pipeline.live import HeuristicExtractor
from pipeline.resolve import supersession_pairs
from pipeline.textsim import TfIdf


def test_ticket_refs():
    assert find_ticket_refs("Fixes BD-101, see also (BD-107) and BD-101 again") == ["BD-101", "BD-107"]
    assert find_ticket_refs("no refs here, just bd101") == []


def test_time_roundtrip():
    assert from_ms(to_ms("2026-09-22T09:40:00Z")) == "2026-09-22T09:40:00Z"
    assert to_ms(None) is None


def test_pr_trailer_roundtrip():
    body = "Fixes BD-101. Exports CSV." + trailer_block("sofia", "2026-09-24T10:00:00Z", "2026-09-25T05:44:00Z")
    text, fields = parse_body(body)
    assert text == "Fixes BD-101. Exports CSV."
    assert fields == {"Authored-by": "sofia", "Scenario-created": "2026-09-24T10:00:00Z", "Scenario-merged": "2026-09-25T05:44:00Z"}
    assert parse_body("plain body") == ("plain body", {})


def _r(id, origin, at):
    return {"id": id, "origin": origin, "at_ms": at, "at": str(at), "text": id}


def test_supersession_reflected_change():
    chain = [_r("v1", "ticket", 1), _r("chat", "chat", 2), _r("v2", "ticket", 3)]
    pairs = supersession_pairs(chain, reflects=lambda new, old: True)
    assert {(p["new"], p["old"]) for p in pairs} == {("chat", "v1"), ("v2", "chat")}


def test_supersession_unrelated_ticket_edit_keeps_drift_open():
    chain = [_r("v1", "ticket", 1), _r("chat", "chat", 2), _r("v2-typo", "ticket", 3)]
    pairs = supersession_pairs(chain, reflects=lambda new, old: False)
    # the chat change is NOT superseded, so the drift query still sees it
    assert ("v2-typo", "chat") not in {(p["new"], p["old"]) for p in pairs}
    assert ("chat", "v1") in {(p["new"], p["old"]) for p in pairs}


def test_supersession_newer_chat_replaces_older_chat_only_when_judged_to():
    chain = [_r("v1", "ticket", 1), _r("c1", "chat", 2), _r("c2", "chat", 3)]
    pairs = {(p["new"], p["old"]) for p in supersession_pairs(chain, lambda n, o: False, replaces=lambda n, o: True)}
    assert pairs == {("c1", "v1"), ("c2", "c1")}


def test_latest_chat_message_does_not_bury_an_open_decision():
    """The noise fix: without a judgment that c2 revises c1 (rules extractor), both stay open."""
    chain = [_r("v1", "ticket", 1), _r("c1", "chat", 2), _r("c2", "chat", 3)]
    pairs = {(p["new"], p["old"]) for p in supersession_pairs(chain, lambda n, o: False, replaces=None)}
    assert pairs == {("c1", "v1")}
    unrelated = {(p["new"], p["old"]) for p in supersession_pairs(chain, lambda n, o: False, replaces=lambda n, o: False)}
    assert unrelated == {("c1", "v1")}


def test_a_less_confident_message_cannot_replace_a_decision():
    chain = [_r("v1", "ticket", 1), {**_r("c1", "chat", 2), "confidence": 0.9}, {**_r("c2", "chat", 3), "confidence": 0.6}]
    pairs = {(p["new"], p["old"]) for p in supersession_pairs(chain, lambda n, o: False, replaces=lambda n, o: True)}
    assert ("c2", "c1") not in pairs


def test_llm_extraction_is_discarded_when_its_evidence_is_not_in_the_message():
    from pipeline.extract import evidence_ok, from_structured

    msg = "Let's change it: send the warning 15 minutes BEFORE the breach."
    good = {
        "is_change": True,
        "kind": "decision",
        "new": "Warn 15 minutes before breach.",
        "confidence": 0.9,
        "evidence_quote": "send the warning 15 minutes   before the breach",
    }
    assert evidence_ok(good["evidence_quote"], msg)
    assert from_structured(good, msg)["kind"] == "decision"
    made_up = {**good, "evidence_quote": "send the warning by SMS"}
    out = from_structured(made_up, msg)
    assert out["kind"] == "other" and out["requirement"] is None and out["guard"] == "evidence_not_in_message"
    assert from_structured({"is_change": False, "kind": "status"}, msg)["kind"] == "status"


def test_tfidf_prefers_topical_doc():
    s = TfIdf({"export": "export tickets csv columns date range", "sla": "sla breach email notification assignee"})
    assert s.best("the csv export needs custom date range")[0] == "export"
    assert s.best("email at breach is too late")[0] == "sla"


def test_heuristic_extractor():
    ex = HeuristicExtractor()
    out = ex.classify([{"id": "a", "text": "Decision: export must support 12 months"}, {"id": "b", "text": "lol nice weekend"}], [])
    assert out["a"]["kind"] == "decision" and out["b"]["kind"] == "other"


def test_grader():
    item = {"must": [["12 months", "a year"], ["custom field"]], "must_not": [["30 days is current"]]}
    assert grade("Now a year of history plus custom fields", item)["score"] == 1.0
    assert grade("Only a year", item)["score"] == 0.5
    assert grade("a year, custom fields; 30 days is current", item)["score"] == 0.0


def test_llm_unavailable_without_key(monkeypatch):
    """No key -> available() is False with a reason, so callers take the rule-based path."""
    import dataclasses

    from pipeline import llm

    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, llm_api_key=""))
    llm._status.update(ok=None, reason="", at=0.0)
    assert llm.available() is False and "not set" in llm.unavailable_reason()


def test_llm_failure_is_cached_as_unavailable(monkeypatch):
    """A key that errors (e.g. 402 insufficient balance) degrades gracefully instead of raising."""
    from pipeline import llm

    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise RuntimeError("Error code: 402 - Insufficient Balance")

    import dataclasses

    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, llm_api_key="sk-test"))
    monkeypatch.setattr(llm, "_client", lambda: Boom)
    llm._status.update(ok=None, reason="", at=0.0)
    assert llm.available() is False and llm.unavailable_reason() == "insufficient balance"
    llm._status.update(ok=None, reason="", at=0.0)


def test_heuristic_reflects_ignores_edit_chatter_and_requires_numbers():
    from pipeline.extract import HeuristicExtractor

    ex = HeuristicExtractor()
    chat = {"text": "the export must support any custom date range up to 12 months (not a fixed 30 days)"}
    prev = "Admins can export tickets created in the last 30 days as a CSV file."
    assert not ex.reflects({"text": prev + " (typo fixed)", "prev_text": prev}, chat)
    assert ex.reflects({"text": "Export any custom date range up to 12 months as CSV.", "prev_text": prev}, chat)
    assert ex.reflects({"text": prev + " Columns: assignee.", "prev_text": prev}, {"text": "Let's add an assignee column, BD-101."})


def test_decision_rights_are_the_tickets_creator_or_assignee():
    from pipeline.resolve import has_decision_rights

    t = {"creator": "maya", "assignee": "sofia"}
    assert has_decision_rights("maya", t) and has_decision_rights("sofia", t)
    assert not has_decision_rights("zara", t) and not has_decision_rights(None, {"creator": None, "assignee": None})


def test_slack_check_names_missing_scopes(monkeypatch):
    """check_setup must say exactly which Slack bot scopes are missing and where to add them."""
    import dataclasses

    import slack_sdk

    from scripts import check_setup as cs

    class Resp(dict):
        headers = {"x-oauth-scopes": "chat:write,channels:read"}

    class FakeClient:
        def __init__(self, token):
            pass

        def auth_test(self):
            return Resp(user="drift", team="acme")

    monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
    monkeypatch.setattr(cs, "settings", dataclasses.replace(cs.settings, slack_bot_token="xoxb-test", slack_app_token="xapp-test"))
    cs.results.clear()
    cs.slack()
    name, ok, detail = cs.results[-1]
    assert not ok and "channels:history" in detail and "users:read" in detail and "Bot Token Scopes" in detail
    assert "chat:write (" not in detail  # granted scopes are not reported


def test_agent_recovers_when_the_provider_rejects_a_tool_call(monkeypatch):
    """Groq validates tool calls server-side: gpt-oss-120b once sent `feature: null`, got a 400, and the whole
    benchmark aborted. The agent must report the rejection to the model and carry on."""
    from types import SimpleNamespace

    from openai import BadRequestError

    from agent import agent
    from pipeline import llm

    calls = {"n": 0}

    def create(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            resp = SimpleNamespace(status_code=400, headers={}, request=None)
            raise BadRequestError("Tool call validation failed: /feature expected string, got null", response=resp, body=None)
        assert "rejected" in kw["messages"][-1]["content"]  # the model is told what went wrong
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="ok"))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)
    monkeypatch.setattr(agent, "_client", lambda: fake)
    out = agent.ask("anything")
    assert out["answer"] == "ok" and out["tool_calls"][0]["tool"] == "(rejected tool call)"


def test_llm_confidence_given_as_a_string_is_parsed_not_crashed_on():
    """gpt-oss-20b returned confidence "0.8" (a string); comparing it with MIN_CONFIDENCE crashed the run."""
    from pipeline.extract import from_structured

    msg = "Decision: exports go to 12 months now."
    base = {"is_change": True, "new": "exports go to 12 months", "kind": "decision", "evidence_quote": "exports go to 12 months"}
    assert from_structured({**base, "confidence": "0.8"}, msg)["confidence"] == 0.8
    assert from_structured({**base, "confidence": "high"}, msg)["confidence"] == 0.0
    assert from_structured({**base, "confidence": None}, msg)["confidence"] == 0.0
