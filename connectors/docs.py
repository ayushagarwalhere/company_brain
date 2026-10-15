"""Docs connector: Markdown product docs (PRDs, design notes, RFCs) with a small frontmatter block.

    ---
    id: DOC-1
    title: PRD — Ticket export
    author: maya
    created: 2026-09-12T06:00:00Z
    updated: 2026-09-15T10:40:00Z
    tickets: BD-101, BD-102
    ---
    body…

A Notion/Confluence connector would emit the same Event; the files stand in for it.
"""
from pathlib import Path

from pipeline.events import Event, find_ticket_refs

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "docs"


def parse(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def documents(directory: Path = DOCS_DIR) -> list[Event]:
    events = []
    for path in sorted(directory.glob("*.md")):
        meta, body = parse(path.read_text(encoding="utf-8"))
        tickets = [t.strip() for t in meta.get("tickets", "").split(",") if t.strip()]
        events.append(Event(
            source="docs", kind="document", id=meta["id"], author=meta["author"], ts=meta["created"],
            text=body, url=f"scenario://docs/{path.name}",
            extra={"title": meta["title"], "updated": meta.get("updated", meta["created"]),
                   "tickets": sorted(set(tickets) | set(find_ticket_refs(body)))},
        ))
    return events
