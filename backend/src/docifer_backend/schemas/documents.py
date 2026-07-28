from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DocumentModalityStatus = Literal[
    "indexed",
    "not_indexed",
    "not_available",
    "failed",
    "unknown",
]


class ModalityIndexStatus(BaseModel):
    status: DocumentModalityStatus
    count: int
    latest_status: str | None = None
    collection_name: str | None = None
    latest_indexed_at: datetime | None = None


class DocumentModalitiesResponse(BaseModel):
    text: ModalityIndexStatus
    table: ModalityIndexStatus
    visual: ModalityIndexStatus


class ArtifactReference(BaseModel):
    path: str | None = Field(default=None, exclude=True)
    exists: bool
    source: str
    generated_by: str
    artifact_type: str


class VisualArtifactReference(BaseModel):
    visual_id: str
    visual_type: str
    page_start: int | None
    artifact_path: str | None = Field(default=None, exclude=True)
    exists: bool
    source: str


class LatestIngestionResponse(BaseModel):
    job_id: str
    status: str
    parser_name: str | None
    parser_version: str | None
    artifact_path: str | None = Field(default=None, exclude=True)
    created_at: datetime
    completed_at: datetime | None


class ParseAuditMetricsResponse(BaseModel):
    page_count: int | None = None
    table_count: int | None = None
    table_candidate_count: int | None = None
    table_like_page_count: int | None = None
    figure_count: int | None = None
    figure_candidate_count: int | None = None
    caption_candidate_count: int | None = None
    empty_page_count: int | None = None
    text_chars_total: int | None = None
    avg_chars_per_page: float | None = None
    parse_error_count: int | None = None
    chunk_count: int | None = None


class DocumentAuditSummaryResponse(BaseModel):
    audit_id: str
    audit_status: str
    quality_status: str | None
    text_readiness: str | None
    table_readiness: str | None
    visual_readiness: str | None
    risk_flags: list[str]
    summary: ParseAuditMetricsResponse | None
    artifact_json: ArtifactReference | None
    artifact_md: ArtifactReference | None
    created_at: datetime


class DocumentSummaryResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    filename: str
    is_uploaded: bool = False
    parser_name: str | None
    latest_ingestion_status: str | None
    quality_status: str | None
    modalities: DocumentModalitiesResponse


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummaryResponse]
    total: int
    limit: int
    offset: int


class DocumentDetailResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    filename: str
    is_uploaded: bool = False
    file_size_bytes: int
    latest_ingestion: LatestIngestionResponse | None
    modalities: DocumentModalitiesResponse
    latest_audit: DocumentAuditSummaryResponse | None
    artifacts: list[ArtifactReference]


class DocumentDeleteResponse(BaseModel):
    document_id: str
    filename: str
    deleted: bool


class DocumentIndexStatusResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    modalities: DocumentModalitiesResponse


class DocumentAuditResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    latest_audit: DocumentAuditSummaryResponse | None
    warning: str | None = None


class DocumentArtifactsResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    artifacts: list[ArtifactReference]
    visual_artifacts: list[VisualArtifactReference]
