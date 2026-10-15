"""Central settings loaded from .env. Import `settings` everywhere instead of reading os.environ."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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


settings = Settings()
