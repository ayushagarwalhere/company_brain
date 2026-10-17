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
    llm_max_retries: int = int(_get("LLM_MAX_RETRIES", "2"))  # raise for rate-limited free tiers (Groq: 10)


settings = Settings()


# ---------------------------------------------------------------- tuning constants (one place, with reasons)
# Extraction: an extracted "requirement change" below this confidence is not written as a change, in the batch
# build and in the live monitor alike. The rules extractor emits 0.7 for every change it finds.
MIN_CONFIDENCE = 0.6
# Resolution: minimum TF-IDF similarity (0..1) for the semantic signals, used only when no hard link exists.
MSG_SIM_THRESHOLD = 0.22  # message -> feature, when the message names no ticket and its thread has no feature
PR_SIM_THRESHOLD = 0.25  # PR -> ticket, among tickets its author owned around the PR's time
IMPL_SIM_THRESHOLD = 0.25  # time-aware IMPLEMENTS fallback: PR text vs. the new chat requirement
# Rules agent: minimum TF-IDF similarity between a question and a feature's name/titles to call it a match.
ROUTER_FEATURE_MIN_SIM = 0.12
# Below this the match is used but the answer says it is low-confidence and names the feature it picked, so a
# question about something the graph doesn't know ("mobile app push notifications" -> SLA breach notifications,
# 0.54) isn't answered silently about the wrong feature. Chosen after looking at the scores of the 15 demo
# questions and ~10 paraphrases (well-matched questions score 0.6-0.93); it does not change any routing.
ROUTER_FEATURE_WEAK_SIM = 0.6
# Involvement weights for "who knows" and knowledge risk (bus factor): one source for both queries.
# Making a decision says more about ownership than writing a PR, a PR more than a ticket, a ticket more than a message.
INVOLVEMENT_WEIGHTS = {"Decision": 5, "PullRequest": 4, "Ticket": 3}
INVOLVEMENT_DEFAULT_WEIGHT = 1  # messages
