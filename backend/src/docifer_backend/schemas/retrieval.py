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
    retrieval_mode: str = Field(default="dense", pattern="^(dense|bm25|hybrid)$")
    verify_citations: bool = False


class CitationResponse(BaseModel):
    citation_id: str
    chunk_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None


class EvidenceResponse(BaseModel):
    citation_id: str
    chunk_id: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    retrieval_mode: str
    text: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None


class CitationVerificationResponse(BaseModel):
    verdict: str
    supported_citation_ids: list[str]
    weak_citation_ids: list[str]
    unsupported_claims: list[str]
    reasoning: str
    revised_answer: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    answer_citations: list[CitationResponse]
    evidence: list[EvidenceResponse]
    retrieved_evidence: list[EvidenceResponse]
    unused_retrieved_evidence: list[EvidenceResponse]
    citation_verification: CitationVerificationResponse | None = None
    debug: dict
