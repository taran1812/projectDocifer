import hmac
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from docifer_backend.api.documents import router as documents_router
from docifer_backend.api.health import router as health_router
from docifer_backend.api.ingestion import router as ingestion_router
from docifer_backend.api.retrieval import router as retrieval_router
from docifer_backend.api.vector import router as vector_router
from docifer_backend.config.settings import get_settings

_UNPROTECTED_PATHS = {"/health", "/ready"}


def create_app() -> FastAPI:
    settings = get_settings()

    docs_url = None if settings.api_key else "/docs"
    redoc_url = None if settings.api_key else "/redoc"

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend API for the Docifer multimodal multi-agent document intelligence system.",
        docs_url=docs_url,
        redoc_url=redoc_url,
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

    if settings.api_key:
        _encoded_key = settings.api_key.encode()

        @app.middleware("http")
        async def require_api_key(request: Request, call_next):
            if request.url.path not in _UNPROTECTED_PATHS:
                provided = request.headers.get("X-API-Key", "").encode()
                if not hmac.compare_digest(provided, _encoded_key):
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Invalid or missing API key."},
                    )
            return await call_next(request)

    app.include_router(health_router)
    app.include_router(ingestion_router)
    app.include_router(retrieval_router)
    app.include_router(vector_router)
    app.include_router(documents_router)

    @app.on_event("startup")
    async def _startup_warnings() -> None:
        if not settings.api_key:
            logger.warning(
                "SECURITY: DOCIFER_API_KEY is not set — all endpoints are unauthenticated. "
                "Do not expose this server on a public network without setting an API key."
            )
        if not settings.api_key or settings.app_env == "development":
            logger.warning(
                "SECURITY: No rate limiting is configured. "
                "The /query endpoint makes live OpenAI API calls on every request. "
                "Do not expose this server publicly without adding rate limiting (e.g. slowapi)."
            )

    return app


app = create_app()
