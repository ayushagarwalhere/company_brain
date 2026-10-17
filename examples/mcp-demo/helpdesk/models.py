from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Ticket:
    id: str
    subject: str
    status: str
    created_at: datetime
    assignee: str | None = None
    custom_fields: dict[str, str] = field(default_factory=dict)  # per-account fields, e.g. {"plan": "Pro", "region": "EU"}
