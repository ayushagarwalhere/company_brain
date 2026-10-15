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
    assert fields == {"Authored-by": "sofia", "Scenario-created": "2026-09-24T10:00:00Z",
                      "Scenario-merged": "2026-09-25T05:44:00Z"}
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


def test_supersession_newer_chat_replaces_older_chat():
    chain = [_r("v1", "ticket", 1), _r("c1", "chat", 2), _r("c2", "chat", 3)]
    pairs = {(p["new"], p["old"]) for p in supersession_pairs(chain, reflects=lambda n, o: False)}
    assert pairs == {("c1", "v1"), ("c2", "c1")}


def test_tfidf_prefers_topical_doc():
    s = TfIdf({"export": "export tickets csv columns date range", "sla": "sla breach email notification assignee"})
    assert s.best("the csv export needs custom date range")[0] == "export"
    assert s.best("email at breach is too late")[0] == "sla"


def test_heuristic_extractor():
    ex = HeuristicExtractor()
    out = ex.classify([{"id": "a", "text": "Decision: export must support 12 months"},
                       {"id": "b", "text": "lol nice weekend"}], [])
    assert out["a"]["kind"] == "decision" and out["b"]["kind"] == "other"


def test_grader():
    item = {"must": [["12 months", "a year"], ["custom field"]], "must_not": [["30 days is current"]]}
    assert grade("Now a year of history plus custom fields", item)["score"] == 1.0
    assert grade("Only a year", item)["score"] == 0.5
    assert grade("a year, custom fields; 30 days is current", item)["score"] == 0.0


def test_llm_unavailable_without_key(monkeypatch):
    """No key -> available() is False with a reason, so callers take the rule-based path."""
    from pipeline import llm
    import dataclasses
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, deepseek_api_key=""))
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
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, deepseek_api_key="sk-test"))
    monkeypatch.setattr(llm, "_client", lambda: Boom)
    llm._status.update(ok=None, reason="", at=0.0)
    assert llm.available() is False and llm.unavailable_reason() == "insufficient balance"
    llm._status.update(ok=None, reason="", at=0.0)
