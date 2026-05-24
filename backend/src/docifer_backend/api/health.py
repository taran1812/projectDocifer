import asyncio

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from docifer_backend.config.settings import get_settings
from docifer_backend.storage.database import check_database_connection
from docifer_backend.storage.qdrant import (
    check_qdrant_connection,
    get_qdrant_collection_checks,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness check: confirms the API process is running."""
    settings = get_settings()

    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness check: confirms critical local dependencies are reachable."""
    database_ready, qdrant_ready = await asyncio.gather(
        asyncio.to_thread(check_database_connection),
        asyncio.to_thread(check_qdrant_connection),
    )

    all_ready = database_ready and qdrant_ready

    response_payload = {
        "status": "ready" if all_ready else "not_ready",
        "checks": {
            "postgres": "ok" if database_ready else "unavailable",
            "qdrant": "ok" if qdrant_ready else "unavailable",
        },
    }
    if qdrant_ready:
        response_payload["checks"].update(
            await asyncio.to_thread(get_qdrant_collection_checks)
        )
    else:
        response_payload["checks"].update(
            {
                "text_collection": "unavailable",
                "table_collection": "unavailable",
                "visual_collection": "unavailable",
            }
        )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if all_ready
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=response_payload,
    )
