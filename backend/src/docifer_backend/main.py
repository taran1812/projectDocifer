from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docifer_backend.api.documents import router as documents_router
from docifer_backend.api.health import router as health_router
from docifer_backend.api.ingestion import router as ingestion_router
from docifer_backend.api.retrieval import router as retrieval_router
from docifer_backend.api.vector import router as vector_router
from docifer_backend.config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend API for the Docifer multimodal multi-agent document intelligence system.",
    )

    cors_origins = settings.parsed_cors_allowed_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_router)
    app.include_router(ingestion_router)
    app.include_router(retrieval_router)
    app.include_router(vector_router)
    app.include_router(documents_router)

    return app


app = create_app()
