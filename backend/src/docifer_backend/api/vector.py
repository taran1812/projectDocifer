from fastapi import APIRouter, HTTPException, status

from docifer_backend.storage.qdrant import (
    get_qdrant_client,
    get_vector_collection_stats,
    list_vector_collection_stats,
    vector_search_config_debug,
)

router = APIRouter(prefix="/vector", tags=["vector"])


@router.get("/collections")
async def list_collections() -> dict:
    return {
        "collections": list_vector_collection_stats(client=get_qdrant_client()),
        "debug": vector_search_config_debug(),
    }


@router.get("/collections/{collection_name}/stats")
async def collection_stats(collection_name: str) -> dict:
    try:
        return get_vector_collection_stats(
            collection_name=collection_name,
            client=get_qdrant_client(),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vector collection not found: {collection_name}",
        ) from exc
