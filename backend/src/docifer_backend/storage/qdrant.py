from functools import lru_cache

from qdrant_client import QdrantClient

from docifer_backend.config.settings import get_settings


@lru_cache
def get_qdrant_client() -> QdrantClient:
    """Create and cache the Qdrant client."""
    settings = get_settings()

    return QdrantClient(
        url=settings.qdrant_url,
    )


def check_qdrant_connection() -> bool:
    """Return True when Qdrant is reachable."""
    try:
        get_qdrant_client().get_collections()
        return True
    except Exception:
        return False
