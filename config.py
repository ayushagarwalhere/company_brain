"""Central settings loaded from .env. Import `settings` everywhere instead of reading os.environ."""
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Windows consoles default to cp1252, which can't print the arrows and quotes our CLIs use
# (ablation tables, digests, retros). Every entry point imports this module, so fix it once here.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() not in ("utf-8", "utf8"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = _get("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(_get("FALKORDB_PORT", "6379") or 6379)
    falkordb_username: str = _get("FALKORDB_USERNAME")
    falkordb_password: str = _get("FALKORDB_PASSWORD")
    falkordb_graph: str = _get("FALKORDB_GRAPH", "company_brain")

    slack_bot_token: str = _get("SLACK_BOT_TOKEN")
    slack_app_token: str = _get("SLACK_APP_TOKEN")
    slack_test_channel_id: str = _get("SLACK_TEST_CHANNEL_ID")

    discord_bot_token: str = _get("DISCORD_BOT_TOKEN")
    discord_guild_id: str = _get("DISCORD_GUILD_ID")

    github_token: str = _get("GITHUB_TOKEN")
    github_repo: str = _get("GITHUB_REPO")

    deepseek_api_key: str = _get("DEEPSEEK_API_KEY")
    deepseek_base_url: str = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = _get("DEEPSEEK_MODEL", "deepseek-chat")

    # Any OpenAI-compatible endpoint. Unset = DeepSeek (the DEEPSEEK_* values above).
    #   Ollama, local and free:  LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=qwen3:8b  LLM_API_KEY=ollama
    #                            LLM_REASONING_EFFORT=none   (qwen3: skip the thinking phase, about 15x faster)
    llm_base_url: str = _get("LLM_BASE_URL") or _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_model: str = _get("LLM_MODEL") or _get("DEEPSEEK_MODEL", "deepseek-chat")
    llm_api_key: str = _get("LLM_API_KEY") or _get("DEEPSEEK_API_KEY")
    llm_reasoning_effort: str = _get("LLM_REASONING_EFFORT")


settings = Settings()


# ---------------------------------------------------------------- tuning constants (one place, with reasons)
# Rules agent: minimum TF-IDF similarity between a question and a feature's name/titles to call it a match.
ROUTER_FEATURE_MIN_SIM = 0.12
