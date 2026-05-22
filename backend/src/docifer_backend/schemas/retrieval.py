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


class TableIndexRequest(BaseModel):
    canonical_path: str = Field(..., description="Path to a canonical parsed document JSON artifact.")
    force_reindex: bool = False


class TableIndexResponse(BaseModel):
    document_id: str
    content_hash: str
    status: str
    table_evidence_count: int
    structured_table_count: int
    markdown_table_count: int
    table_like_text_count: int
    collection_name: str
    reused_existing: bool


class QueryRequest(BaseModel):
    question: str
    content_hash: str | None = None
    top_k: int = Field(default=4, ge=1, le=10)
    retrieval_mode: str = Field(default="dense", pattern="^(dense|bm25|hybrid)$")
    evidence_mode: str = Field(default="text", pattern="^(text|table|auto)$")
    table_top_k: int = Field(default=4, ge=1, le=10)
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


class TableCitationResponse(BaseModel):
    citation_id: str
    evidence_type: str
    table_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    table_type: str
    table_readiness: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None


class TableEvidenceResponse(BaseModel):
    citation_id: str
    table_id: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    retrieval_mode: str
    table_type: str
    source_kind: str
    table_readiness: str
    raw_text: str
    markdown_table: str | None = None
    structured_json: dict | None = None
    section_heading: str | None = None
    source_path: str
    source_artifact_path: str
    source_chunk_id: str | None = None
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
    table_citations: list[TableCitationResponse] = []
    answer_citations: list[CitationResponse]
    evidence: list[EvidenceResponse]
    table_evidence: list[TableEvidenceResponse] = []
    retrieved_evidence: list[EvidenceResponse]
    unused_retrieved_evidence: list[EvidenceResponse]
    unused_table_evidence: list[TableEvidenceResponse] = []
    citation_verification: CitationVerificationResponse | None = None
    debug: dict


class VisualIndexRequest(BaseModel):
    canonical_path: str = Field(..., description="Path to a canonical parsed document JSON artifact.")
    force_reindex: bool = False


class VisualIndexResponse(BaseModel):
    document_id: str
    content_hash: str
    status: str
    page_render_count: int
    figure_candidate_count: int
    visual_record_count: int
    collection_name: str
    reused_existing: bool


class VisualRetrieveRequest(BaseModel):
    question: str
    content_hash: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: str = Field(default="visual_hybrid", pattern="^(visual_dense|visual_bm25|visual_hybrid)$")
    debug: bool = False


class VisualCandidateResponse(BaseModel):
    visual_id: str
    document_id: str
    content_hash: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    retrieval_mode: str
    visual_type: str
    source_kind: str
    page_start: int | None
    page_end: int | None
    artifact_path: str | None = None
    caption: str | None = None
    section_heading: str | None = None
    nearby_text: str | None = None
    figure_label: str | None = None
    visual_readiness: str
    filename: str
    source_path: str
    source_artifact_path: str


class VisualRetrieveResponse(BaseModel):
    candidates: list[VisualCandidateResponse]
    debug: dict = Field(default_factory=dict)
