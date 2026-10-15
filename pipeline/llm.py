"""DeepSeek client (OpenAI-compatible) with JSON output and an on-disk cache.

The cache makes pipeline runs reproducible and cheap: the same prompt never hits
the API twice. Delete data/llm_cache/ to force fresh calls.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from config import settings

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_cache"


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def chat_json(system: str, user: str, *, temperature: float = 0.0, use_cache: bool = True) -> dict:
    key = hashlib.sha256(f"{settings.deepseek_model}\n{system}\n{user}".encode()).hexdigest()[:24]
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    resp = _client().chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    out = json.loads(resp.choices[0].message.content)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def chat_text(system: str, user: str, *, temperature: float = 0.2) -> str:
    resp = _client().chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp.choices[0].message.content
