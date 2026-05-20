from pydantic import BaseModel, Field


class IngestPdfRequest(BaseModel):
    source_path: str = Field(..., description="Project-relative or absolute path to a local PDF.")
    force_reprocess: bool = False


class IngestionJobResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    artifact_path: str | None
    reused_existing: bool
    error_message: str | None = None
