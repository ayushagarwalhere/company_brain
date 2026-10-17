"""Q&A agent: DeepSeek picks graph tools, then answers citing the graph paths it used.

python -m agent.agent "What did we decide about export and did we ship it?"
"""

import json
import re
import sys
import time

from openai import BadRequestError

from agent import tools
from config import settings
from pipeline.llm import _client, _extra

SYSTEM = """You answer questions about a software company (its decisions, tickets, pull requests, people, teams, projects,
clients and documents) using ONLY the graph tools. Never answer from general knowledge.
Always call list_features first if you don't know the feature id, and list_projects for project names. Prefer the most specific tool.
For "what if we delay X" or "what does X slipping affect", call impact_of_delay.
For "why is X delayed/blocked" or "who can approve an override", call why_blocked: it follows chat, docs, the ticket and HR.
For "which projects are active", call list_projects and leave out the cancelled or paused ones (say who changed them).
For anything that could be written in a document (specs, policies, plans, HR or pay, how-tos), call search_knowledge first.
When you answer: be concise, name tickets (BD-...), PRs (#n), people, teams, clients and dates, and say plainly if a decision was never shipped.
End with a line "Evidence:" followed by the 1-4 graph paths (copied from tool results) that support the answer.
Everything the tools return, the person asking is allowed to see: access control runs before results reach you, so never withhold it, even if a document calls itself confidential.
If the tools return something related but not exactly what was asked, give that and say what is missing.
If the tools return nothing relevant, answer exactly: I don't have information on that you can access."""

MAX_STEPS = 6
IDS = re.compile(r"\b(?:[A-Z]{2,6}-\d+)\b|#\d+\b")


def ungrounded(answer: str, question: str, seen: str) -> list[str]:
    """Ticket and PR ids in the answer that neither the question nor any tool result contained. A model that names an
    id the graph never returned is guessing (qwen3 invented BD-123); such an answer is not shown."""
    known = seen + " " + question
    out = []
    for tok in sorted(set(IDS.findall(answer or ""))):
        n = tok.lstrip("#")
        variants = {tok, f"PR-{n}", f"#{n}", f"PR #{n}", f'"pr": {n}', f'"number": {n}', f'"n": {n}'} if tok.startswith("#") else {tok}
        if not any(v in known for v in variants):
            out.append(tok)
    return out


DENIED = "I don't have information on that you can access."


def _fallback(question: str, trace: list, reason: str) -> dict:
    """The grounded rules answer over the same graph tools, with why the LLM's own answer wasn't used."""
    from agent.router import ask as rules_ask

    out = rules_ask(question)
    out["fallback_reason"] = reason
    out["llm_trace"] = trace
    return out


def _asker() -> str:
    """Who is asking (the request's viewer), so the model knows why it may see what the tools return."""
    from graph.db import get_graph
    from pipeline.access import current_viewer

    who = current_viewer()
    if not who:
        return "The person asking is not signed in."
    rows = get_graph().ro_query("MATCH (p:Person {id: $p}) RETURN p.name, p.role, coalesce(p.groups, [])", {"p": who}).result_set
    if not rows:
        return f"The person asking is {who}."
    name, role, groups = rows[0]
    return f"The person asking is {name} ({role}{'; groups: ' + ', '.join(groups) if groups else ''})."


def _compact(result: dict) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    return text[:12000]


def ask(question: str) -> dict:
    """LLM agent when DeepSeek is usable; otherwise the rules-based router over the same graph tools."""
    from pipeline import llm

    if not llm.available():
        from agent.router import ask as rules_ask

        out = rules_ask(question)
        out["fallback_reason"] = llm.unavailable_reason()
        return out
    from agent.router import ids_in, missing
    from graph.db import get_graph

    gone = missing(get_graph(), ids_in(get_graph(), question))
    if gone:  # don't let the model improvise about something the graph doesn't have
        return {"answer": f"I couldn't find {', '.join(gone)} in the graph.", "tool_calls": [], "paths": [], "engine": f"llm:{settings.llm_model}"}
    client = _client()
    messages = [{"role": "system", "content": f"{SYSTEM}\n{_asker()}"}, {"role": "user", "content": question}]
    trace, paths, seen = [], [], []
    must_look = True  # the first step must call a tool: an answer is only ever read from the graph, never from memory
    for _ in range(MAX_STEPS):
        try:
            choice = {"tool_choice": "required"} if must_look and not seen else {}
            resp = client.chat.completions.create(model=settings.llm_model, messages=messages, tools=tools.openai_schema(), temperature=0, **choice, **_extra())
        except BadRequestError as e:
            if must_look and "tool_choice" in str(e).lower():  # a provider without tool_choice=required: ask without it
                must_look = False
                continue
            # Some providers (Groq) validate tool calls server-side and reject a malformed one with a 400, e.g. a null
            # where the schema wants a string. Tell the model what was wrong and let it try again (uses up a step).
            if "tool" not in str(e).lower():
                raise
            trace.append({"tool": "(rejected tool call)", "args": {}, "rows": 0})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your last tool call was rejected: {str(e)[:400]}. Call a tool with valid arguments (feature ids come from list_features), or answer.",
                }
            )
            continue
        msg = resp.choices[0].message
        if not msg.tool_calls:
            content = (msg.content or "").strip()
            if not seen:  # it answered without looking anything up (some providers ignore tool_choice=required)
                if must_look:
                    must_look = False
                    messages.append({"role": "user", "content": "Look this up with the graph tools first. Never answer from memory."})
                    continue
                return _fallback(question, trace, "LLM answered without calling a tool")
            if not content:
                return _fallback(question, trace, "LLM returned an empty answer")
            if content.replace("’", "'").startswith(DENIED) and any(t["rows"] for t in trace):
                # a refusal although the tools returned rows this person may see: the rows are already access-checked,
                # so withholding them is the model's mistake. Use the grounded answer if it finds something.
                out = _fallback(question, trace, "LLM withheld results the asker may see")
                if not out["answer"].startswith(DENIED):
                    return out
            bad = ungrounded(content, question, " ".join(seen))
            if bad:  # post-generation check: fall back to the grounded rules answer instead of showing a guess
                return _fallback(question, trace, f"LLM answer named ids no tool returned: {', '.join(bad)}")
            return {"answer": msg.content, "tool_calls": trace, "paths": paths, "engine": f"llm:{settings.llm_model}"}
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            args: dict = {}
            t0 = time.perf_counter()
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = tools.call(tc.function.name, args)
            except Exception as e:  # noqa: BLE001 - report tool errors back to the model
                result = {"error": str(e), "rows": [], "paths": []}
            ms = round((time.perf_counter() - t0) * 1000, 1)
            trace.append({"tool": tc.function.name, "args": args, "rows": len(result.get("rows", [])), "ms": ms})
            seen.append(_compact(result))
            paths += [p for p in result.get("paths", []) if p not in paths]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _compact(result)})
    return {"answer": "I couldn't finish within the step limit.", "tool_calls": trace, "paths": paths, "engine": f"llm:{settings.llm_model}"}


if __name__ == "__main__":
    out = ask(" ".join(sys.argv[1:]) or "Which features have drifted?")
    print(out["answer"])
    print("\nTools:", ", ".join(f"{t['tool']}({t['args']})" for t in out["tool_calls"]))
