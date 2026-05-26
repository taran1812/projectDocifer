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
export type QueryScope = "single" | "all";

export interface QueryRequest {
  question: string;
  scope: QueryScope;
  content_hash?: string;
  max_documents: number;
  max_evidence_per_document: number;
  top_k: number;
  retrieval_mode: RetrievalMode;
  evidence_mode: EvidenceMode;
  table_top_k: number;
  visual_top_k: number;
  verify_citations: boolean;
}

export interface Citation {
  citation_id: string;
  source_path: string;
  source_artifact_path: string;
  page_start?: number | null;
  page_end?: number | null;
  score: number;
  doc_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  content_hash?: string | null;
}

export interface Evidence {
  citation_id: string;
  score: number;
  retrieval_mode: string;
  text?: string;
  raw_text?: string;
  markdown_table?: string | null;
  visual_type?: string;
  source_kind?: string;
  artifact_path?: string | null;
  doc_id?: string | null;
  filename?: string | null;
  source_path: string;
  page_start?: number | null;
  page_end?: number | null;
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
  retrieved_evidence: Evidence[];
  unused_retrieved_evidence: Evidence[];
  unused_table_evidence: Evidence[];
  unused_visual_evidence: Evidence[];
  citation_verification?: CitationVerification | null;
  debug: Record<string, unknown>;
}
