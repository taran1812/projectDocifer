from functools import lru_cache
from typing import Any

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


def default_vector_collection_names() -> list[str]:
    settings = get_settings()
    names = [
        settings.qdrant_text_collection,
        settings.qdrant_table_collection,
        settings.qdrant_visual_collection,
    ]
    return list(dict.fromkeys(names))


def get_qdrant_collection_checks(
    *,
    client: QdrantClient | None = None,
) -> dict[str, str]:
    """Return non-fatal collection-level readiness checks."""
    qdrant_client = client or get_qdrant_client()
    settings = get_settings()
    checks = {
        "text_collection": settings.qdrant_text_collection,
        "table_collection": settings.qdrant_table_collection,
        "visual_collection": settings.qdrant_visual_collection,
    }
    statuses: dict[str, str] = {}
    for check_name, collection_name in checks.items():
        try:
            statuses[check_name] = (
                "ok"
                if qdrant_client.collection_exists(collection_name)
                else "missing"
            )
        except Exception:
            statuses[check_name] = "unavailable"
    return statuses


def list_vector_collection_stats(
    *,
    client: QdrantClient | None = None,
    collection_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    qdrant_client = client or get_qdrant_client()
    names = collection_names or default_vector_collection_names()
    stats: list[dict[str, Any]] = []
    for collection_name in names:
        if not qdrant_client.collection_exists(collection_name):
            stats.append(_missing_collection_stats(collection_name))
            continue
        stats.append(
            get_vector_collection_stats(
                collection_name=collection_name,
                client=qdrant_client,
            )
        )
    return stats


def get_vector_collection_stats(
    *,
    collection_name: str,
    client: QdrantClient | None = None,
) -> dict[str, Any]:
    qdrant_client = client or get_qdrant_client()
    if not qdrant_client.collection_exists(collection_name):
        raise KeyError(collection_name)
    info = qdrant_client.get_collection(collection_name)
    vector_params = _first_vector_params(info)
    distance = getattr(vector_params, "distance", None)
    status = getattr(info, "status", "unknown")
    hnsw_config = getattr(getattr(info, "config", None), "hnsw_config", None)
    return {
        "collection_name": collection_name,
        "points_count": int(getattr(info, "points_count", 0) or 0),
        "indexed_vectors_count": int(getattr(info, "indexed_vectors_count", 0) or 0),
        "vector_size": getattr(vector_params, "size", None),
        "distance": getattr(distance, "value", str(distance)) if distance is not None else None,
        "payload_indexes": sorted((getattr(info, "payload_schema", None) or {}).keys()),
        "status": getattr(status, "value", str(status)),
        "hnsw_m": getattr(hnsw_config, "m", None),
        "hnsw_ef_construct": getattr(hnsw_config, "ef_construct", None),
    }


def vector_search_config_debug() -> dict[str, Any]:
    settings = get_settings()
    return {
        "vector_search_exact": settings.qdrant_exact_search,
        "vector_search_ef": settings.qdrant_search_ef,
        "qdrant_hnsw_m": settings.qdrant_hnsw_m,
        "qdrant_hnsw_ef_construct": settings.qdrant_hnsw_ef_construct,
        "qdrant_create_payload_indexes": settings.qdrant_create_payload_indexes,
    }


def _missing_collection_stats(collection_name: str) -> dict[str, Any]:
    return {
        "collection_name": collection_name,
        "points_count": 0,
        "indexed_vectors_count": 0,
        "vector_size": None,
        "distance": None,
        "payload_indexes": [],
        "status": "missing",
        "hnsw_m": None,
        "hnsw_ef_construct": None,
    }


def _first_vector_params(info: Any) -> Any:
    vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
    if isinstance(vectors, dict):
        return next(iter(vectors.values()), None)
    return vectors
