"""Q&A agent: DeepSeek picks graph tools, then answers citing the graph paths it used.

    python -m agent.agent "What did we decide about export and did we ship it?"
"""
import json
import sys

from agent import tools
from config import settings
from pipeline.llm import _client

SYSTEM = """You answer questions about a software team's decisions, tickets and pull requests using ONLY the graph tools.
Always call list_features first if you don't know the feature id. Prefer the most specific tool.
When you answer: be concise, name tickets (BD-...), PRs (#n), people and dates, and say plainly if a decision was never shipped.
End with a line "Evidence:" followed by the 1-4 graph paths (copied from tool results) that support the answer.
If the tools return nothing relevant, say you don't know."""

MAX_STEPS = 6


def _compact(result: dict) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    return text[:12000]


def ask(question: str) -> dict:
    """LLM agent when DEEPSEEK_API_KEY is set; otherwise the rules-based router over the same graph tools."""
    if not settings.deepseek_api_key:
        from agent.router import ask as rules_ask
        return rules_ask(question)
    client = _client()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    trace, paths = [], []
    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(model=settings.deepseek_model, messages=messages,
                                              tools=tools.openai_schema(), temperature=0)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content, "tool_calls": trace, "paths": paths, "engine": "deepseek"}
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            try:
                result = tools.call(tc.function.name, args)
            except Exception as e:  # noqa: BLE001 - report tool errors back to the model
                result = {"error": str(e), "rows": [], "paths": []}
            trace.append({"tool": tc.function.name, "args": args, "rows": len(result.get("rows", []))})
            paths += [p for p in result.get("paths", []) if p not in paths]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _compact(result)})
    return {"answer": "I couldn't finish within the step limit.", "tool_calls": trace, "paths": paths, "engine": "deepseek"}


if __name__ == "__main__":
    out = ask(" ".join(sys.argv[1:]) or "Which features have drifted?")
    print(out["answer"])
    print("\nTools:", ", ".join(f"{t['tool']}({t['args']})" for t in out["tool_calls"]))
