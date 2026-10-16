"""LLM client for any OpenAI-compatible endpoint, with JSON output and an on-disk cache.

DeepSeek by default; Ollama (local, free), Groq, OpenRouter, ... by setting LLM_BASE_URL / LLM_MODEL /
LLM_API_KEY (see config.py). Only the base URL and model change, the calls are the same.

The cache makes pipeline runs reproducible and cheap: the same (model, prompt) never hits
the API twice. Delete data/llm_cache/ to force fresh calls.
"""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from config import settings

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_cache"
THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    if not settings.llm_api_key:
        raise RuntimeError("no LLM key set (LLM_API_KEY or DEEPSEEK_API_KEY)")
    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def _extra() -> dict:
    """Provider-specific options: qwen3 on Ollama answers about 15x faster with its thinking phase off."""
    return {"reasoning_effort": settings.llm_reasoning_effort} if settings.llm_reasoning_effort else {}


def model_name() -> str:
    return settings.llm_model


def _strip_think(text: str | None) -> str:
    """Reasoning models served through Ollama may prepend a <think>...</think> block."""
    return THINK.sub("", text or "")


_status: dict = {"ok": None, "reason": "", "at": 0.0}


def available(ttl: float = 300.0) -> bool:
    """Whether the LLM can actually answer right now (key set AND a tiny call succeeds).

    A key can be valid but unusable (no balance, revoked, network down), so callers
    check this and fall back to the rule-based path instead of failing. Cached for `ttl` s.
    """
    import time
    if not settings.llm_api_key:
        _status.update(ok=False, reason="LLM key not set")
        return False
    if _status["ok"] is not None and time.time() - _status["at"] < ttl:
        return _status["ok"]
    try:
        _client().chat.completions.create(model=settings.llm_model, max_tokens=1,
                                          messages=[{"role": "user", "content": "ping"}], **_extra())
        _status.update(ok=True, reason="")
    except Exception as e:  # noqa: BLE001 - any failure means "use the fallback"
        msg = str(e)
        reason = ("insufficient balance" if "402" in msg else "invalid key" if "401" in msg else type(e).__name__)
        _status.update(ok=False, reason=reason)
    _status["at"] = time.time()
    return _status["ok"]


def unavailable_reason() -> str:
    return _status["reason"]


_refreshing = {"on": False}


def peek(ttl: float = 300.0) -> tuple[bool | None, str]:
    """Non-blocking status for read paths (dashboard stats): returns the last known result at once and,
    if it's missing or stale, refreshes it in a background thread. None = not checked yet."""
    import threading
    import time
    if not settings.llm_api_key:
        return False, "LLM key not set"
    stale = _status["ok"] is None or time.time() - _status["at"] >= ttl
    if stale and not _refreshing["on"]:
        _refreshing["on"] = True

        def run():
            try:
                available(ttl=0)
            finally:
                _refreshing["on"] = False
        threading.Thread(target=run, daemon=True).start()
    return _status["ok"], _status["reason"] if _status["ok"] is False else ("checking…" if _status["ok"] is None else "")


def chat_json(system: str, user: str, *, temperature: float = 0.0, use_cache: bool = True) -> dict:
    key = hashlib.sha256(f"{settings.llm_model}\n{system}\n{user}".encode()).hexdigest()[:24]
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    resp = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=temperature, **_extra(),
    )
    out = json.loads(_strip_think(resp.choices[0].message.content))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def chat_text(system: str, user: str, *, temperature: float = 0.2) -> str:
    resp = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature, **_extra(),
    )
    return _strip_think(resp.choices[0].message.content)
