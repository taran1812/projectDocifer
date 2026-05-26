export type ModalityStatusValue =
  | "indexed"
  | "not_indexed"
  | "not_available"
  | "failed"
  | "unknown";

export interface ModalityIndexStatus {
  status: ModalityStatusValue;
  count: number;
  latest_status?: string | null;
  collection_name?: string | null;
  latest_indexed_at?: string | null;
}

export interface DocumentModalities {
  text: ModalityIndexStatus;
  table: ModalityIndexStatus;
  visual: ModalityIndexStatus;
}

export interface DocumentSummary {
  document_id: string;
  doc_id?: string | null;
  content_hash: string;
  filename: string;
  source_path: string;
  parser_name?: string | null;
  latest_ingestion_status?: string | null;
  quality_status?: string | null;
  modalities: DocumentModalities;
}

export interface DocumentListResponse {
  documents: DocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: string;
}

export interface ReadyResponse {
  status: string;
  checks: Record<string, string>;
}

export type EvidenceMode = "text" | "table" | "visual" | "auto";
export type RetrievalMode = "dense" | "bm25" | "hybrid";
export type QueryScope = "single" | "doc_ids" | "all";

export interface QueryRequest {
  question: string;
  scope: QueryScope;
  content_hash?: string;
  doc_ids?: string[];
  document_ids?: string[];
  max_documents: number;
  max_evidence_per_document: number;
  top_k: number;
  retrieval_mode: RetrievalMode;
  evidence_mode: EvidenceMode;
  table_top_k: number;
  visual_top_k: number;
  verify_citations: boolean;
  rerank?: boolean | null;
  rerank_top_n?: number | null;
}

export interface Citation {
  citation_id: string;
  chunk_id?: string;
  evidence_type?: string;
  table_id?: string;
  visual_id?: string;
  source_path: string;
  source_artifact_path: string;
  artifact_path?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  table_type?: string;
  table_readiness?: string;
  visual_type?: string;
  visual_readiness?: string;
  score: number;
  doc_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  content_hash?: string | null;
  dense_score?: number | null;
  lexical_score?: number | null;
  hybrid_score?: number | null;
  rerank_score?: number | null;
  pre_rerank_rank?: number | null;
  post_rerank_rank?: number | null;
  reranker_model?: string | null;
}

export interface Evidence {
  citation_id: string;
  chunk_id?: string;
  table_id?: string;
  visual_id?: string;
  score: number;
  dense_score?: number | null;
  lexical_score?: number | null;
  hybrid_score?: number | null;
  rerank_score?: number | null;
  pre_rerank_rank?: number | null;
  post_rerank_rank?: number | null;
  reranker_model?: string | null;
  retrieval_mode: string;
  text?: string;
  raw_text?: string;
  markdown_table?: string | null;
  visual_type?: string;
  source_kind?: string;
  table_type?: string;
  table_readiness?: string;
  structured_json?: Record<string, unknown> | null;
  section_heading?: string | null;
  source_chunk_id?: string | null;
  artifact_path?: string | null;
  caption?: string | null;
  nearby_text?: string | null;
  figure_label?: string | null;
  visual_readiness?: string;
  doc_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  content_hash?: string | null;
  source_path: string;
  source_artifact_path?: string;
  page_start?: number | null;
  page_end?: number | null;
}

export interface VisualObservation {
  citation_id: string;
  visual_id: string;
  observation_type: string;
  question_answered: boolean;
  extracted_facts: string[];
  visible_entities: string[];
  numeric_values: string[];
  confidence: number;
  limitations: string[];
  abstain_reason: string;
  supported: boolean;
  reasoning: string;
}

export interface CitationVerification {
  verdict: string;
  supported_citation_ids: string[];
  weak_citation_ids: string[];
  unsupported_claims: string[];
  reasoning: string;
  revised_answer?: string | null;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  table_citations: Citation[];
  visual_citations: Citation[];
  answer_citations: Citation[];
  evidence: Evidence[];
  table_evidence: Evidence[];
  visual_evidence: Evidence[];
  visual_observations: VisualObservation[];
  retrieved_evidence: Evidence[];
  unused_retrieved_evidence: Evidence[];
  unused_table_evidence: Evidence[];
  unused_visual_evidence: Evidence[];
  citation_verification?: CitationVerification | null;
  debug: Record<string, unknown>;
}
