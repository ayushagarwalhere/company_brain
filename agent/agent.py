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

SYSTEM = """You answer questions about a software team's decisions, tickets and pull requests using ONLY the graph tools.
Always call list_features first if you don't know the feature id. Prefer the most specific tool.
When you answer: be concise, name tickets (BD-...), PRs (#n), people and dates, and say plainly if a decision was never shipped.
End with a line "Evidence:" followed by the 1-4 graph paths (copied from tool results) that support the answer.
If the tools return nothing relevant, say you don't know."""

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
    client = _client()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    trace, paths, seen = [], [], []
    for _ in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(model=settings.llm_model, messages=messages, tools=tools.openai_schema(), temperature=0, **_extra())
        except BadRequestError as e:
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
            bad = ungrounded(msg.content or "", question, " ".join(seen))
            if bad:  # post-generation check: fall back to the grounded rules answer instead of showing a guess
                from agent.router import ask as rules_ask

                out = rules_ask(question)
                out["fallback_reason"] = f"LLM answer named ids no tool returned: {', '.join(bad)}"
                out["llm_trace"] = trace
                return out
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
