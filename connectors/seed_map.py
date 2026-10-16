"""Maps platform message ids to scenario messages.

Slack and Discord can't backdate messages, and seeded messages are all posted by
one bot. The seeders record, for each platform message id, which scenario message
it carries; connectors use this to recover the original author, timestamp and
thread. Messages not in the map (e.g. posted live by a judge) keep their real values.
"""

import json
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "seed_maps"


def load(platform: str) -> dict[str, dict]:
    path = DIR / f"{platform}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(platform: str, mapping: dict[str, dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{platform}.json").write_text(json.dumps(mapping, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
