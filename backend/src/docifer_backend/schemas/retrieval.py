from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    scope: Literal["single", "doc_ids", "all"] = "single"
    content_hash: str | None = None
    doc_ids: list[str] | None = None
    document_ids: list[str] | None = None
    max_documents: int = Field(default=5, ge=1, le=25)
    max_evidence_per_document: int = Field(default=3, ge=1, le=10)
    top_k: int = Field(default=4, ge=1, le=10)
    retrieval_mode: str = Field(default="dense", pattern="^(dense|bm25|hybrid)$")
    evidence_mode: str = Field(default="text", pattern="^(text|table|visual|auto)$")
    table_top_k: int = Field(default=4, ge=1, le=10)
    visual_top_k: int = Field(default=3, ge=1, le=5)
    verify_citations: bool = False
    rerank: bool | None = None
    rerank_top_n: int | None = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def validate_request(self):
        if self.rerank_top_n is not None and self.rerank_top_n < self.top_k:
            raise ValueError("rerank_top_n must be greater than or equal to top_k.")
        selected_ids = (self.doc_ids or []) + (self.document_ids or [])
        if self.scope == "single":
            if self.content_hash and selected_ids:
                raise ValueError("scope='single' accepts content_hash or one document identifier, not both.")
            if not self.content_hash and len(selected_ids) != 1:
                raise ValueError("scope='single' requires content_hash or exactly one doc_id/document_id.")
        elif self.scope == "doc_ids":
            if self.content_hash:
                raise ValueError("scope='doc_ids' does not accept content_hash.")
            if not selected_ids:
                raise ValueError("scope='doc_ids' requires doc_ids or document_ids.")
        elif self.scope == "all" and (self.content_hash or selected_ids):
            raise ValueError("scope='all' cannot be combined with document filters.")
        return self


class CitationResponse(BaseModel):
    citation_id: str
    chunk_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    score: float
    doc_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    content_hash: str | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None
    reranker_model: str | None = None


class EvidenceResponse(BaseModel):
    citation_id: str
    chunk_id: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None
    reranker_model: str | None = None
    retrieval_mode: str
    text: str
    doc_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    content_hash: str | None = None
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
    doc_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    content_hash: str | None = None
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
    doc_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    content_hash: str | None = None
    markdown_table: str | None = None
    structured_json: dict | None = None
    section_heading: str | None = None
    source_path: str
    source_artifact_path: str
    source_chunk_id: str | None = None
    page_start: int | None
    page_end: int | None


class VisualCitationResponse(BaseModel):
    citation_id: str
    evidence_type: str
    visual_id: str
    source_path: str
    source_artifact_path: str
    artifact_path: str | None = None
    page_start: int | None
    page_end: int | None
    visual_type: str
    visual_readiness: str
    score: float
    doc_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    content_hash: str | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None


class VisualEvidenceResponse(BaseModel):
    citation_id: str
    visual_id: str
    document_id: str
    content_hash: str
    doc_id: str | None = None
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


class VisualObservationResponse(BaseModel):
    citation_id: str
    visual_id: str
    observation_type: str
    question_answered: bool
    extracted_facts: list[str]
    visible_entities: list[str]
    numeric_values: list[str]
    confidence: float
    limitations: list[str]
    abstain_reason: str
    supported: bool
    reasoning: str


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
    visual_citations: list[VisualCitationResponse] = []
    answer_citations: list[CitationResponse]
    evidence: list[EvidenceResponse]
    table_evidence: list[TableEvidenceResponse] = []
    visual_evidence: list[VisualEvidenceResponse] = []
    visual_observations: list[VisualObservationResponse] = []
    retrieved_evidence: list[EvidenceResponse]
    unused_retrieved_evidence: list[EvidenceResponse]
    unused_table_evidence: list[TableEvidenceResponse] = []
    unused_visual_evidence: list[VisualEvidenceResponse] = []
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
