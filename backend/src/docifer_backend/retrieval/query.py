from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass

from qdrant_client import QdrantClient

from docifer_backend.config.settings import get_settings
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.providers.base import AIProvider, CitationGroundingVerdict, GroundingEvidence
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.bm25 import BM25Retriever
from docifer_backend.retrieval.hybrid import merge_hybrid_results
from docifer_backend.retrieval.tables.reasoning import reason_over_table_evidence
from docifer_backend.retrieval.tables.retriever import TableRetriever
from docifer_backend.retrieval.tables.schemas import (
    TableCitation,
    TableQueryResult,
    TableReasoningResult,
    format_table_evidence_for_embedding,
)
from docifer_backend.retrieval.vector_store import RetrievedChunk, search_text_chunks
from docifer_backend.storage.database import get_session_factory
from docifer_backend.storage.qdrant import get_qdrant_client


@dataclass(frozen=True)
class QueryCitation:
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


@dataclass(frozen=True)
class QueryOutcome:
    answer: str
    citations: list[QueryCitation]
    table_citations: list[TableCitation]
    evidence: list[RetrievedChunk]
    table_evidence: list[TableQueryResult]
    unused_evidence: list[RetrievedChunk]
    unused_table_evidence: list[TableQueryResult]
    citation_verification: CitationGroundingVerdict | None
    debug: dict


class TextQueryService:
    def __init__(
        self,
        *,
        ai_provider: AIProvider | None = None,
        qdrant_client: QdrantClient | None = None,
        session_factory: sessionmaker[Session] | None = None,
        collection_name: str | None = None,
        table_collection_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.session_factory = session_factory or get_session_factory()
        self.collection_name = collection_name or settings.qdrant_text_collection
        self.bm25_retriever = BM25Retriever(session_factory=self.session_factory)
        self.table_collection_name = table_collection_name or settings.qdrant_table_collection
        self.table_retriever = TableRetriever(
            ai_provider=self.ai_provider,
            qdrant_client=self.qdrant_client,
            session_factory=self.session_factory,
            collection_name=self.table_collection_name,
        )

    def query(
        self,
        *,
        question: str,
        content_hash: str | None = None,
        top_k: int = 4,
        retrieval_mode: str = "dense",
        evidence_mode: str = "text",
        table_top_k: int = 4,
        verify_citations: bool = False,
    ) -> QueryOutcome:
        retrieval_mode = retrieval_mode.lower()
        evidence_mode = evidence_mode.lower()
        if evidence_mode not in {"text", "table", "auto"}:
            raise ValueError(f"Unsupported evidence mode: {evidence_mode}")

        table_intent = detect_table_intent(question)
        should_retrieve_text = evidence_mode in {"text", "auto"}
        should_retrieve_tables = evidence_mode == "table" or (
            evidence_mode == "auto" and table_intent["detected"]
        )

        retrieved: list[RetrievedChunk] = []
        if should_retrieve_text:
            retrieved = self._retrieve(
                question=question,
                content_hash=content_hash,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
            )

        table_retrieval_latency_ms = None
        table_results: list[TableQueryResult] = []
        table_reasoning: TableReasoningResult | None = None
        if should_retrieve_tables:
            start = time.perf_counter()
            table_results = self.table_retriever.search(
                query=question,
                top_k=table_top_k,
                content_hash=content_hash,
                retrieval_mode="table_hybrid",
            )
            table_retrieval_latency_ms = int((time.perf_counter() - start) * 1000)
            if table_results:
                table_reasoning = reason_over_table_evidence(
                    question=question,
                    tables=table_results,
                )

        debug = {
            "collection_name": self.collection_name,
            "top_k": top_k,
            "retrieval_mode": retrieval_mode,
            "verify_citations": verify_citations,
            "evidence_mode": evidence_mode,
            "retrieved_count": len(retrieved),
            "table_indexed_collection": self.table_collection_name,
            "table_top_k": table_top_k,
            "table_retrieval_mode": "table_hybrid",
            "table_retrieval_requested": should_retrieve_tables,
            "table_retrieval_latency_ms": table_retrieval_latency_ms,
            "table_retrieved_count": len(table_results),
            "table_intent_detected": table_intent["detected"],
            "table_intent_score": table_intent["score"],
            "table_intent_matches": table_intent["matches"],
            "table_reasoning_used": table_reasoning is not None,
            "table_reasoning_status": table_reasoning.status if table_reasoning else None,
            "table_reasoning": asdict(table_reasoning) if table_reasoning else None,
            "content_hash_scope": "specific" if content_hash else "all",
        }

        if not retrieved and not table_results:
            answer = (
                "I could not find table evidence in the indexed documents to answer this question."
                if evidence_mode == "table"
                else "I do not have enough evidence from the indexed document to answer."
            )
            return QueryOutcome(
                answer=answer,
                citations=[],
                table_citations=[],
                evidence=[],
                table_evidence=[],
                unused_evidence=[],
                unused_table_evidence=[],
                citation_verification=None,
                debug=debug,
            )

        grounding = [
            GroundingEvidence(
                citation_id=f"C{index}",
                text=chunk.text,
                source=_format_source(chunk),
            )
            for index, chunk in enumerate(retrieved, start=1)
        ]
        grounding.extend(
            _table_grounding_evidence(table_results, table_reasoning)
        )
        answer = self.ai_provider.generate_grounded_answer(
            question=question,
            evidence=grounding,
        )
        citation_verification = None
        if verify_citations:
            citation_verification = self.ai_provider.verify_citation_grounding(
                question=question,
                answer=answer,
                evidence=grounding,
            )
            if citation_verification.verdict == "unsupported":
                answer = (
                    citation_verification.revised_answer
                    or "I do not have enough evidence from the indexed document to answer."
                )
            elif citation_verification.revised_answer:
                answer = citation_verification.revised_answer

        cited_ids = _extract_citation_ids(answer)
        citations = _build_answer_citations(retrieved, cited_ids)
        table_citations = _build_table_answer_citations(table_results, cited_ids)
        unused_evidence = [
            chunk
            for index, chunk in enumerate(retrieved, start=1)
            if f"C{index}" not in cited_ids
        ]
        unused_table_evidence = [
            table
            for index, table in enumerate(table_results, start=1)
            if f"T{index}" not in cited_ids
        ]

        debug.update(
            {
                "answer_citation_count": len(citations),
                "answer_table_citation_count": len(table_citations),
                "unused_retrieved_count": len(unused_evidence),
                "unused_table_retrieved_count": len(unused_table_evidence),
                "citation_verification": (
                    asdict(citation_verification)
                    if citation_verification is not None
                    else None
                ),
            }
        )

        return QueryOutcome(
            answer=answer,
            citations=citations,
            table_citations=table_citations,
            evidence=retrieved,
            table_evidence=table_results,
            unused_evidence=unused_evidence,
            unused_table_evidence=unused_table_evidence,
            citation_verification=citation_verification,
            debug=debug,
        )

    def _retrieve(
        self,
        *,
        question: str,
        content_hash: str | None,
        top_k: int,
        retrieval_mode: str,
    ) -> list[RetrievedChunk]:
        if retrieval_mode == "dense":
            query_vector = self.ai_provider.embed_texts([question])[0]
            return search_text_chunks(
                self.qdrant_client,
                collection_name=self.collection_name,
                query_vector=query_vector,
                top_k=top_k,
                content_hash=content_hash,
            )
        if retrieval_mode == "bm25":
            return self.bm25_retriever.search(
                query=question,
                top_k=top_k,
                content_hash=content_hash,
            )
        if retrieval_mode == "hybrid":
            query_vector = self.ai_provider.embed_texts([question])[0]
            dense_results = search_text_chunks(
                self.qdrant_client,
                collection_name=self.collection_name,
                query_vector=query_vector,
                top_k=max(top_k * 2, top_k),
                content_hash=content_hash,
            )
            lexical_results = self.bm25_retriever.search(
                query=question,
                top_k=max(top_k * 2, top_k),
                content_hash=content_hash,
            )
            return merge_hybrid_results(
                dense_results=dense_results,
                lexical_results=lexical_results,
                top_k=top_k,
            )
        raise ValueError(f"Unsupported retrieval mode: {retrieval_mode}")


def _format_source(chunk: RetrievedChunk) -> str:
    if chunk.page_start and chunk.page_end and chunk.page_start != chunk.page_end:
        page_label = f"pages {chunk.page_start}-{chunk.page_end}"
    elif chunk.page_start:
        page_label = f"page {chunk.page_start}"
    else:
        page_label = "page unknown"
    return f"{chunk.filename}, {page_label}, chunk {chunk.chunk_id}"


def _format_table_source(table: TableQueryResult) -> str:
    if table.page_start and table.page_end and table.page_start != table.page_end:
        page_label = f"pages {table.page_start}-{table.page_end}"
    elif table.page_start:
        page_label = f"page {table.page_start}"
    else:
        page_label = "page unknown"
    return f"table:{table.table_id}, {table.filename}, {page_label}"


def _table_grounding_evidence(
    table_results: list[TableQueryResult],
    table_reasoning: TableReasoningResult | None,
) -> list[GroundingEvidence]:
    if (
        table_reasoning
        and table_reasoning.status == "supported"
        and table_reasoning.selected_observation
        and table_reasoning.reasoning_text
    ):
        selected_index = table_reasoning.selected_observation.evidence_index
        selected_table = table_results[selected_index - 1] if 0 < selected_index <= len(table_results) else None
        if selected_table is not None:
            return [
                GroundingEvidence(
                    citation_id=table_reasoning.selected_observation.citation_id,
                    text=(
                        f"{table_reasoning.reasoning_text}\n\n"
                        "Supporting table evidence:\n"
                        f"{format_table_evidence_for_embedding(selected_table)}"
                    ),
                    source=_format_table_source(selected_table),
                )
            ]

    return [
        GroundingEvidence(
            citation_id=f"T{index}",
            text=format_table_evidence_for_embedding(table),
            source=_format_table_source(table),
        )
        for index, table in enumerate(table_results, start=1)
    ]


def _extract_citation_ids(answer: str) -> set[str]:
    return {
        match.upper()
        for match in re.findall(r"\[(C\d+|T\d+)\]", answer, flags=re.IGNORECASE)
    }


def _build_answer_citations(
    retrieved: list[RetrievedChunk],
    cited_ids: set[str],
) -> list[QueryCitation]:
    citations: list[QueryCitation] = []
    for index, chunk in enumerate(retrieved, start=1):
        citation_id = f"C{index}"
        if citation_id not in cited_ids:
            continue
        citations.append(
            QueryCitation(
                citation_id=citation_id,
                chunk_id=chunk.chunk_id,
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=chunk.score,
                dense_score=chunk.dense_score,
                lexical_score=chunk.lexical_score,
                hybrid_score=chunk.hybrid_score,
            )
        )
    return citations


def _build_table_answer_citations(
    table_results: list[TableQueryResult],
    cited_ids: set[str],
) -> list[TableCitation]:
    citations: list[TableCitation] = []
    for index, table in enumerate(table_results, start=1):
        citation_id = f"T{index}"
        if citation_id not in cited_ids:
            continue
        citations.append(
            TableCitation(
                citation_id=citation_id,
                evidence_type="table",
                table_id=table.table_id,
                source_path=table.source_path,
                source_artifact_path=table.source_artifact_path,
                page_start=table.page_start,
                page_end=table.page_end,
                table_type=table.table_type,
                table_readiness=table.table_readiness,
                score=table.score,
                dense_score=table.dense_score,
                lexical_score=table.lexical_score,
                hybrid_score=table.hybrid_score,
            )
        )
    return citations


def detect_table_intent(question: str) -> dict:
    normalized = question.lower()
    matches: list[str] = []
    explicit_matches: list[str] = []
    explicit_terms = ["table", "row", "column"]
    for term in explicit_terms:
        if re.search(rf"\b{re.escape(term)}s?\b", normalized):
            explicit_matches.append(term)
    matches.extend(explicit_matches)

    numeric_matches = sorted(set(re.findall(r"\b20\d\d\b|\$|%|\bbillion\b|\bmillion\b", normalized)))
    financial_terms = [
        "net income",
        "net interest income",
        "noninterest revenue",
        "revenue",
        "segment",
        "total",
        "assets",
        "liabilities",
        "highest",
        "lowest",
        "compare",
    ]
    financial_matches = [term for term in financial_terms if term in normalized]
    matches.extend(numeric_matches)
    matches.extend(financial_matches)
    deduped_matches = list(dict.fromkeys(matches))
    detected = bool(explicit_matches) or (bool(numeric_matches) and bool(financial_matches))
    return {
        "detected": detected,
        "score": len(deduped_matches),
        "matches": deduped_matches,
    }
