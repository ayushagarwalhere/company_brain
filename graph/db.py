"""FalkorDB connection helper."""
from functools import lru_cache

from falkordb import FalkorDB

from config import settings


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username or None,
        password=settings.falkordb_password or None,
    )


def get_graph(name: str | None = None):
    """One graph per organisation; defaults to FALKORDB_GRAPH."""
    return get_db().select_graph(name or settings.falkordb_graph)
