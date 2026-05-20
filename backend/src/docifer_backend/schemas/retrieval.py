from pydantic import BaseModel, Field


class TextIndexRequest(BaseModel):
    canonical_path: str = Field(..., description="Path to a canonical parsed document JSON artifact.")
    force_reindex: bool = False


class TextIndexResponse(BaseModel):
    document_id: str
    content_hash: str
    status: str
    chunk_count: int
    collection_name: str
    reused_existing: bool


class QueryRequest(BaseModel):
    question: str
    content_hash: str | None = None
    top_k: int = Field(default=4, ge=1, le=10)


class CitationResponse(BaseModel):
    citation_id: str
    chunk_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    score: float


class EvidenceResponse(BaseModel):
    citation_id: str
    chunk_id: str
    score: float
    text: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    evidence: list[EvidenceResponse]
    debug: dict
