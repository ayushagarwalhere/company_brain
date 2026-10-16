"""FalkorDB connection helper, with one isolated graph per organisation.

The API sets the current org per request (X-Org header or ?org=); every get_graph() call in that
request then resolves to that org's graph. No org = the default graph (FALKORDB_GRAPH).
"""
import re
from contextvars import ContextVar
from functools import lru_cache

from falkordb import FalkorDB

from config import settings

ORG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_org: ContextVar[str | None] = ContextVar("org", default=None)


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username or None,
        password=settings.falkordb_password or None,
    )


def org_graph_name(org: str | None) -> str:
    """Graph name for an org. The default org keeps FALKORDB_GRAPH; others get their own isolated graph."""
    if not org or org == "default":
        return settings.falkordb_graph
    if not ORG_RE.match(org):
        raise ValueError(f"invalid org id {org!r}")
    return f"{settings.falkordb_graph}__{org}"


def set_org(org: str | None):
    """Sets the org for the current context; returns a token for ContextVar.reset()."""
    if org:
        org_graph_name(org)  # validates
    return _org.set(org or None)


def current_org() -> str:
    return _org.get() or "default"


def current_graph_name() -> str:
    return org_graph_name(_org.get())


def get_graph(name: str | None = None):
    """Explicit name wins (CLI, tests); otherwise the current org's graph."""
    return get_db().select_graph(name or current_graph_name())


def list_orgs() -> list[str]:
    prefix = f"{settings.falkordb_graph}__"
    names = get_db().list_graphs()
    orgs = ["default"] if settings.falkordb_graph in names else []
    return orgs + sorted(n[len(prefix):] for n in names if n.startswith(prefix))
