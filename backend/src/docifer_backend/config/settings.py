from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from the project root .env file."""

    app_name: str = "Docifer"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_key: str | None = None

    database_url: str = "postgresql+psycopg://docifer_user:docifer_password@localhost:5432/docifer"

    qdrant_url: str = "http://localhost:6333"

    llm_provider: str = "openai"

    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_answer_model: str = "gpt-5.4-mini"
    openai_vision_model: str = "gpt-4o-mini"
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
    docling_max_file_size_bytes: int = 500_000_000
    upload_max_file_size_bytes: int = 1_000_000_000
    qdrant_text_collection: str = "docifer_text_chunks"
    qdrant_table_collection: str = "docifer_table_evidence"
    qdrant_visual_collection: str = "docifer_visual_evidence"
    qdrant_upsert_batch_size: int = 128
    qdrant_exact_search: bool = False
    qdrant_search_ef: int = 64
    qdrant_hnsw_m: int = 16
    qdrant_hnsw_ef_construct: int = 100
    qdrant_create_payload_indexes: bool = True
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_candidate_top_n: int = 20
    reranker_device: str = "auto"
    reranker_batch_size: int = 8
    reranker_max_length: int = 512
    golden_eval_path: str = "docifer_phase1_corpus_and_golden_eval_v1.xlsx"
    eval_runs_dir: str = "evals/runs"

    text_chunk_size: int = 1200
    text_chunk_overlap: int = 200

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def _validate_chunk_settings(self) -> "Settings":
        if self.text_chunk_size < 200:
            raise ValueError(f"text_chunk_size must be >= 200, got {self.text_chunk_size}")
        if self.text_chunk_overlap < 0:
            raise ValueError(f"text_chunk_overlap must be >= 0, got {self.text_chunk_overlap}")
        if self.text_chunk_overlap >= self.text_chunk_size:
            raise ValueError(
                f"text_chunk_overlap ({self.text_chunk_overlap}) must be < text_chunk_size ({self.text_chunk_size})"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
