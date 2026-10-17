"""The published numbers (docs/RESULTS.md) must match the committed result files, so a code change that moves a number
can't leave the write-up behind (the ablation stale-PR row and the qwen3 stale-PR cell once did)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "docs" / "RESULTS.md").read_text(encoding="utf-8")  # the full tables; the README summarises them


def result(name):
    return json.loads((ROOT / "benchmark" / "results" / name).read_text(encoding="utf-8"))


def row(label: str) -> str:
    """The README table row whose first cell starts with `label`."""
    line = next((x for x in README.splitlines() if x.startswith(f"| {label}")), None)
    assert line, f"no README row starting with {label!r}"
    return line


def nums(line: str) -> list[str]:
    return re.findall(r"\d+\.\d+|\d+/\d+", line.replace("**", ""))


def test_demo_qa_table_matches_result_files():
    rules = result("latest.json")["summary"]
    llm = result("latest_llm_qwen3-8b.json")["summary"]
    oss = result("latest_llm_openai-gpt-oss-120b.json")["summary"]
    cases = [
        ("graph, rules agent", rules["graph (rules agent, no LLM)"]),
        ("retrieval top-3, extractive", rules["baseline (extractive top-3, no LLM)"]),
        ("retrieval top-25, extractive", rules["baseline (extractive top-25, no LLM)"]),
        ("graph, **LLM agent", llm["graph (LLM agent, qwen3:8b)"]),
        ("retrieval top-25 → **qwen3", llm["baseline (TF-IDF top-25 -> qwen3:8b)"]),
        ("graph, **LLM agent (gpt-oss", oss["graph (LLM agent, openai/gpt-oss-120b)"]),
        ("retrieval top-25 → **gpt-oss", oss["baseline (TF-IDF top-25 -> openai/gpt-oss-120b)"]),
    ]
    for label, s in cases:
        got = nums(row(label))
        assert got[:2] == [f"{s['mean_score']:.2f}", f"{s['passed']}/{s['questions']}"], (label, got, s)


def test_ablation_version_reasoning_row_matches():
    s = next(x for x in result("ablation.json") if x["config"].startswith("− version reasoning"))["scores"]
    got = nums(row("− version reasoning"))
    want = [f"{s[k][m]:.2f}" for k in ("message_to_feature", "requirement_changes", "drift_requirements", "drift_stale_prs") for m in ("precision", "recall")]
    assert got == want, (got, want)


def test_qwen3_stale_pr_cell_matches():
    s = result("resolution_llm_qwen3-8b.json")
    got = nums(row("stale PRs / stale docs"))
    assert got[2:] == [f"{s[k][m]:.2f}" for k in ("drift_stale_prs", "drift_stale_docs") for m in ("precision", "recall")], got
