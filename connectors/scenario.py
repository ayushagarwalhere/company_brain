"""Offline connector: replays the synthetic scenario files directly.

Used for development and for the benchmark, so results don't depend on Slack or
Discord being reachable. The live connectors produce the same event ids, so the
graph is identical whichever path is used.
"""

import json
from pathlib import Path

from pipeline.events import Event

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario"


def _load(name: str):
    return json.loads((SCENARIO / name).read_text(encoding="utf-8"))


def people() -> list[dict]:
    return _load("people.json")


def sprints() -> list[dict]:
    return _load("sprints.json")


def message_url(m: dict) -> str:
    return f"scenario://{m['platform']}/{m['channel']}/{m['id']}"


def messages() -> list[Event]:
    return [
        Event(
            source=m["platform"],
            kind="message",
            id=m["id"],
            author=m["author"],
            ts=m["ts"],
            text=m["text"],
            url=message_url(m),
            channel=m["channel"],
            thread_of=m.get("thread_of"),
        )
        for m in _load("messages.json")
    ]
