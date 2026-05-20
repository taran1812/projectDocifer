from fastapi import FastAPI

from docifer_backend.api.health import router as health_router
from docifer_backend.api.ingestion import router as ingestion_router
from docifer_backend.config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend API for the Docifer multimodal multi-agent document intelligence system.",
    )

    app.include_router(health_router)
    app.include_router(ingestion_router)

    return app


app = create_app()
