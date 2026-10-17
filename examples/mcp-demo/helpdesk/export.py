"""Ticket export for admins (BD-101)."""

from helpdesk.models import Ticket


def export_csv(tickets: list[Ticket], **options) -> str:
    """Returns the CSV an admin downloads from the ticket list."""
    raise NotImplementedError("BD-101")
