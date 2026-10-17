# Two recorded runs: "implement BD-101"

Same app, same prompt, same model; the only difference is whether Claude Code can reach the company-brain MCP server.
Recorded on 2026-10-18 with Claude Code 2.1.301, headless (`claude -p "implement BD-101" --model sonnet`), against the
demo company's graph. There is no CLAUDE.md: the only hint to check first is the MCP server's own instructions. Shell
commands were not allowed in either run, so neither could run its code. Below: each run's final message as printed,
then the file it wrote.

## Without MCP (`--strict-mcp-config`, no servers)

> I implemented `export_csv` in `helpdesk/export.py`, but I couldn't run it. The permission prompt for my test command was denied, so the code is untested.
>
> - **Rows:** it includes tickets created in the last 30 days, measured from the current time.
> - **Columns:** `id`, `subject`, `status`, `created_at` (ISO format) and `assignee`. An unassigned ticket gets an empty assignee cell.
> - **Escaping:** it uses Python's `csv` module, so commas and quotes in subjects are escaped correctly.
> - **Test hook:** passing `now=<datetime>` overrides the reference time.
>
> I left out three things the ticket doesn't cover:
> - **Admin check:** the function has no user to check, so admin-only access has to be enforced by whatever calls it.
> - **`custom_fields`:** these aren't exported, since the ticket lists only five columns.
> - **Spreadsheet formulas:** a subject starting with `=`, `+`, `-` or `@` could run as a formula when opened in Excel. I can sanitize those if you want.
>
> Timezone-aware `created_at` values would fail the comparison against the naive `datetime.now()`. The current model uses naive datetimes, so I left that alone.

```python
"""Ticket export for admins (BD-101)."""

import csv
import io
from datetime import datetime, timedelta

from helpdesk.models import Ticket

COLUMNS = ["id", "subject", "status", "created_at", "assignee"]
WINDOW = timedelta(days=30)


def export_csv(tickets: list[Ticket], **options) -> str:
    """Returns the CSV an admin downloads from the ticket list.

    Includes tickets created in the last 30 days. Pass `now` to override the
    reference time (useful for tests).
    """
    now = options.get("now") or datetime.now()
    cutoff = now - WINDOW

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for t in tickets:
        if t.created_at < cutoff:
            continue
        writer.writerow([
            t.id,
            t.subject,
            t.status,
            t.created_at.isoformat(),
            t.assignee or "",
        ])
    return out.getvalue()
```

## With MCP (`--mcp-config .mcp.json`)

It called `current_spec("BD-101")` before writing code.

> I implemented BD-101 in `helpdesk/export.py`, but I couldn't run it. The permission prompt for my smoke test was declined, so none of this has been tested.
>
> **Which requirement I built:** I followed Maya Chen's decision in Slack #support-escalations on 2026-09-22, not the ticket text. The ticket still says "last 30 days, 5 columns". Her decision is that the export supports any custom date range up to 12 months and includes all custom fields as extra columns.
>
> **What `export_csv(tickets, *, start, end)` does now:**
> - **Date range:** It includes tickets with `start <= created_at <= end`. It raises `ValueError` if `end` is before `start` or the range is longer than 12 months.
> - **Columns:** It writes `id, subject, status, created_at, assignee`, then one column per custom field, sorted by name. The custom columns are the union of fields on the exported tickets, and a ticket missing a field gets an empty cell.
>
> **Things to know:**
> - **PR #6:** It already shipped the old 30-day version, but this checkout only had a stub that raised `NotImplementedError`. I edited that stub, so this change should go on top of PR #6 rather than as a parallel implementation.
> - **Stale docs:** PRD DOC-1 ("PRD — Ticket export", last updated 2026-09-15) and the BD-101 ticket text are out of date. Maya Chen or Sofia Alvarez should update them.
> - **Choice for you:** I made `start` and `end` required keyword arguments rather than defaulting them. Say if you'd rather default to the last 30 days.
> - **PR description:** It should cite the decision as Maya Chen, Slack #support-escalations, 2026-09-22.
>
> I haven't committed anything.

```python
"""Ticket export for admins (BD-101)."""

import csv
import io
from datetime import datetime

from helpdesk.models import Ticket

BASE_COLUMNS = ["id", "subject", "status", "created_at", "assignee"]
MAX_RANGE_MONTHS = 12


def _add_months(dt: datetime, months: int) -> datetime:
    """dt shifted by whole months, clamping the day to the target month's length."""
    index = dt.year * 12 + (dt.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    # Last day of target month: day before the 1st of the following month.
    next_first = datetime(year + (month == 12), month % 12 + 1, 1)
    last_day = (next_first - datetime(year, month, 1)).days
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def export_csv(
    tickets: list[Ticket], *, start: datetime, end: datetime, **options
) -> str:
    """Returns the CSV an admin downloads from the ticket list.

    Includes tickets created in [start, end], any custom range up to 12 months.
    Columns: id, subject, status, created_at, assignee, then one column per
    custom field (sorted by name) found on the exported tickets.
    """
    if end < start:
        raise ValueError("end must not be before start")
    if end > _add_months(start, MAX_RANGE_MONTHS):
        raise ValueError(f"date range may not exceed {MAX_RANGE_MONTHS} months")

    selected = [t for t in tickets if start <= t.created_at <= end]
    custom_columns = sorted({k for t in selected for k in t.custom_fields})

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(BASE_COLUMNS + custom_columns)
    for t in selected:
        writer.writerow(
            [t.id, t.subject, t.status, t.created_at.isoformat(), t.assignee or ""]
            + [t.custom_fields.get(c, "") for c in custom_columns]
        )
    return out.getvalue()
```

Two runs are an example, not a measurement: a model can still skip a tool. What the MCP server guarantees is that the
current requirement, its source and the stale PR are one call away, with the graph path behind each fact.
