from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from the project root .env file."""

    app_name: str = "Docifer"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = "postgresql://docifer_user:docifer_password@localhost:5432/docifer"

    qdrant_url: str = "http://localhost:6333"

    llm_provider: str = "openai"

    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_answer_model: str = "gpt-5.4-mini"
    openai_embedding_batch_size: int = 64

    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    vertex_default_model: str | None = None
    vertex_fallback_model: str | None = None

    langsmith_tracing: bool = True
    langsmith_api_key: str | None = None
    langsmith_project: str = "docifer-dev"

    raw_pdf_dir: str = "datasets/raw_pdfs"
    processed_data_dir: str = "datasets/processed"
    artifacts_dir: str = "artifacts"
    pdf_parser_backend: str = "auto"
    docling_max_file_size_bytes: int = 1_000_000
    qdrant_text_collection: str = "docifer_text_chunks"
    qdrant_upsert_batch_size: int = 128
    golden_eval_path: str = "docifer_phase1_corpus_and_golden_eval_v1.xlsx"
    eval_runs_dir: str = "evals/runs"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
