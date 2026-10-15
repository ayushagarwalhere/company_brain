"""Mock ticket connector: reads Linear-style JSON files from data/mock_tickets/."""
import json
from pathlib import Path

from pipeline.events import Event

TICKETS_DIR = Path(__file__).resolve().parent.parent / "data" / "mock_tickets"


def tickets(directory: Path = TICKETS_DIR) -> list[Event]:
    events = []
    for path in sorted(directory.glob("*.json")):
        t = json.loads(path.read_text(encoding="utf-8"))
        events.append(Event(
            source="tickets", kind="ticket", id=t["id"], author=t["creator"], ts=t["createdAt"],
            text=f"{t['title']}\n\n{t['description']}", url=t.get("url", ""),
            extra={
                "title": t["title"],
                "description": t["description"],
                "state": t["state"],
                "priority": t.get("priority"),
                "labels": t.get("labels", []),
                "assignee": t.get("assignee"),
                "sprint": t.get("cycle"),
                "updated_at": t["updatedAt"],
                "completed_at": t.get("completedAt"),
                # Every description version is kept: extraction turns each into STATES edges
                # stamped with the version time, so drift is judged against what the
                # ticket said at that moment, not just its latest text.
                "versions": [h for h in t.get("history", []) if h.get("field") == "description"],
            },
        ))
    return events
