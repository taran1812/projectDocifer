from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass, replace

from qdrant_client import QdrantClient

from docifer_backend.config.settings import get_settings
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.providers.base import (
    AIProvider,
    CitationGroundingVerdict,
    GroundingEvidence,
    VisualInterpretationResult,
)
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.providers.openai_provider import ANSWER_PROMPT_VERSION
from docifer_backend.retrieval.bm25 import BM25Retriever
from docifer_backend.retrieval.document_registry import (
    DocumentScopeResolver,
    QueryDocumentRef,
    ScopeResolution,
)
from docifer_backend.retrieval.hybrid import merge_hybrid_results
from docifer_backend.retrieval.reranking import CrossEncoderReranker, RerankerUnavailableError
from docifer_backend.retrieval.tables.reasoning import reason_over_table_evidence
from docifer_backend.retrieval.tables.retriever import TableRetriever
from docifer_backend.retrieval.tables.schemas import (
    TableCitation,
    TableQueryResult,
    TableReasoningResult,
    format_table_evidence_for_embedding,
)
from docifer_backend.retrieval.vector_store import (
    RetrievedChunk,
    search_text_chunks,
    vector_search_debug,
)
from docifer_backend.retrieval.visuals.interpretation import (
    build_visual_evidence_inputs,
    visual_interpretation_debug,
    visual_observations_to_grounding_evidence,
)
from docifer_backend.retrieval.visuals.retriever import VisualRetriever
from docifer_backend.retrieval.visuals.schemas import (
    VisualCitation,
    VisualQueryResult,
)
from docifer_backend.storage.database import get_session_factory
from docifer_backend.storage.qdrant import get_qdrant_client


_ABSTENTION_MARKERS = (
    "do not have enough evidence",
    "don't have enough evidence",
    "insufficient evidence",
    "cannot answer",
    "cannot determine",
    "not enough evidence",
    "i do not have",
    "i don't have",
)


def _is_abstention(answer: str) -> bool:
    normalised = (
        answer.lower()
        .replace("don't", "do not")
        .replace("can't", "cannot")
        .replace("doesn't", "does not")
    )
    return any(m in normalised for m in _ABSTENTION_MARKERS)


def _is_missing_vector_collection_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "collection" in message and (
        "not found" in message
        or "doesn't exist" in message
        or "does not exist" in message
    )


def _disabled_rerank_debug(
    *,
    rerank_requested: bool,
    reranker_model: str,
    candidate_top_n: int,
) -> dict:
    return {
        "rerank_requested": rerank_requested,
        "rerank_used": False,
        "reranker_model": reranker_model if rerank_requested else None,
        "reranker_status": "not_applicable" if rerank_requested else "disabled",
        "rerank_candidate_top_n": candidate_top_n if rerank_requested else None,
        "rerank_candidate_count": None,
        "rerank_latency_ms": None,
        "pre_rerank_top_chunk_ids": [],
        "post_rerank_top_chunk_ids": [],
        "rerank_error": None,
    }


@dataclass(frozen=True)
class QueryCitation:
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


@dataclass(frozen=True)
class QueryOutcome:
    answer: str
    citations: list[QueryCitation]
    table_citations: list[TableCitation]
    visual_citations: list[VisualCitation]
    evidence: list[RetrievedChunk]
    table_evidence: list[TableQueryResult]
    visual_evidence: list[VisualQueryResult]
    unused_evidence: list[RetrievedChunk]
    unused_table_evidence: list[TableQueryResult]
    unused_visual_evidence: list[VisualQueryResult]
    visual_interpretation: VisualInterpretationResult | None
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
        visual_collection_name: str | None = None,
        reranker: object | None = None,
        document_scope_resolver: DocumentScopeResolver | None = None,
    ) -> None:
        settings = get_settings()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.session_factory = session_factory or get_session_factory()
        self.collection_name = collection_name or settings.qdrant_text_collection
        self.reranker_enabled_default = settings.reranker_enabled
        self.reranker_model = settings.reranker_model
        self.reranker_candidate_top_n = settings.reranker_candidate_top_n
        self.reranker_device = settings.reranker_device
        self.reranker_batch_size = settings.reranker_batch_size
        self.reranker_max_length = settings.reranker_max_length
        self._reranker = reranker
        self.document_scope_resolver = document_scope_resolver or DocumentScopeResolver(
            session_factory=self.session_factory
        )
        self.bm25_retriever = BM25Retriever(session_factory=self.session_factory)
        self.table_collection_name = table_collection_name or settings.qdrant_table_collection
        self.table_retriever = TableRetriever(
            ai_provider=self.ai_provider,
            qdrant_client=self.qdrant_client,
            session_factory=self.session_factory,
            collection_name=self.table_collection_name,
        )
        self.visual_collection_name = visual_collection_name or settings.qdrant_visual_collection
        self.visual_retriever = VisualRetriever(
            ai_provider=self.ai_provider,
            qdrant_client=self.qdrant_client,
            session_factory=self.session_factory,
            collection_name=self.visual_collection_name,
        )

    async def query(
        self,
        *,
        question: str,
        scope: str = "single",
        content_hash: str | None = None,
        doc_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        max_documents: int = 5,
        max_evidence_per_document: int = 3,
        top_k: int = 4,
        retrieval_mode: str = "dense",
        evidence_mode: str = "text",
        table_top_k: int = 4,
        visual_top_k: int = 3,
        verify_citations: bool = False,
        rerank: bool | None = None,
        rerank_top_n: int | None = None,
    ) -> QueryOutcome:
        return await asyncio.to_thread(
            self.query_sync,
            question=question,
            scope=scope,
            content_hash=content_hash,
            doc_ids=doc_ids,
            document_ids=document_ids,
            max_documents=max_documents,
            max_evidence_per_document=max_evidence_per_document,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
            evidence_mode=evidence_mode,
            table_top_k=table_top_k,
            visual_top_k=visual_top_k,
            verify_citations=verify_citations,
            rerank=rerank,
            rerank_top_n=rerank_top_n,
        )

    def query_sync(
        self,
        *,
        question: str,
        scope: str = "single",
        content_hash: str | None = None,
        doc_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        max_documents: int = 5,
        max_evidence_per_document: int = 3,
        top_k: int = 4,
        retrieval_mode: str = "dense",
        evidence_mode: str = "text",
        table_top_k: int = 4,
        visual_top_k: int = 3,
        verify_citations: bool = False,
        rerank: bool | None = None,
        rerank_top_n: int | None = None,
    ) -> QueryOutcome:
        retrieval_mode = retrieval_mode.lower()
        evidence_mode = evidence_mode.lower()
        if evidence_mode not in {"text", "table", "visual", "auto"}:
            raise ValueError(f"Unsupported evidence mode: {evidence_mode}")
        rerank_requested = self.reranker_enabled_default if rerank is None else rerank
        rerank_candidate_top_n = rerank_top_n or self.reranker_candidate_top_n
        if rerank_requested and rerank_candidate_top_n < top_k:
            raise ValueError("rerank_top_n must be greater than or equal to top_k.")
        if rerank_requested and rerank_candidate_top_n > 50:
            raise ValueError("rerank_top_n must be less than or equal to 50.")

        table_intent = detect_table_intent(question)
        visual_intent = detect_visual_intent(question)
        should_retrieve_text = evidence_mode in {"text", "auto"}
        should_retrieve_tables = evidence_mode == "table" or (
            evidence_mode == "auto" and table_intent["detected"]
        )
        should_retrieve_visuals = evidence_mode == "visual" or (
            evidence_mode == "auto" and visual_intent["detected"]
        )
        _validate_scope_arguments(
            scope=scope,
            content_hash=content_hash,
            doc_ids=doc_ids,
            document_ids=document_ids,
            max_documents=max_documents,
            max_evidence_per_document=max_evidence_per_document,
        )
        evidence_types = {
            evidence_type
            for evidence_type, requested in (
                ("text", should_retrieve_text),
                ("table", should_retrieve_tables),
                ("visual", should_retrieve_visuals),
            )
            if requested
        }
        scope_resolution = self.document_scope_resolver.resolve(
            scope=scope,
            content_hash=content_hash,
            doc_ids=doc_ids,
            document_ids=document_ids,
            evidence_types=evidence_types,
        )
        scoped_content_hash = content_hash if scope == "single" else None
        scoped_content_hashes = scope_resolution.content_hashes
        is_multi_document_scope = scope != "single"
        context_pool_top_k = (
            _multi_document_candidate_top_k(
                scope=scope,
                top_k=top_k,
                table_top_k=table_top_k,
                visual_top_k=visual_top_k,
                max_documents=max_documents,
                max_evidence_per_document=max_evidence_per_document,
            )
            if is_multi_document_scope
            else top_k
        )

        retrieved: list[RetrievedChunk] = []
        rerank_debug = _disabled_rerank_debug(
            rerank_requested=rerank_requested,
            reranker_model=self.reranker_model,
            candidate_top_n=rerank_candidate_top_n,
        )
        if should_retrieve_text:
            retrieved, rerank_debug = self._retrieve_with_optional_rerank(
                question=question,
                content_hash=scoped_content_hash,
                content_hashes=scoped_content_hashes,
                top_k=context_pool_top_k,
                retrieval_mode=retrieval_mode,
                rerank=rerank_requested,
                rerank_top_n=rerank_candidate_top_n,
            )

        table_retrieval_latency_ms = None
        table_results: list[TableQueryResult] = []
        table_reasoning: TableReasoningResult | None = None
        if should_retrieve_tables:
            start = time.perf_counter()
            table_results = self.table_retriever.search(
                query=question,
                top_k=max(table_top_k, context_pool_top_k) if is_multi_document_scope else table_top_k,
                content_hash=scoped_content_hash,
                content_hashes=scoped_content_hashes,
                retrieval_mode="table_hybrid",
            )
            if not table_results and evidence_mode == "table":
                retry_table_top_k = min(table_top_k * 2, 8)
                table_results = self.table_retriever.search(
                    query=question,
                    top_k=retry_table_top_k,
                    content_hash=scoped_content_hash,
                    content_hashes=scoped_content_hashes,
                    retrieval_mode="table_hybrid",
                )
            table_retrieval_latency_ms = int((time.perf_counter() - start) * 1000)

        visual_retrieval_latency_ms = None
        visual_results: list[VisualQueryResult] = []
        visual_interpretation: VisualInterpretationResult | None = None
        if should_retrieve_visuals:
            start = time.perf_counter()
            visual_results = self.visual_retriever.search(
                query=question,
                top_k=max(visual_top_k, context_pool_top_k) if is_multi_document_scope else visual_top_k,
                content_hash=scoped_content_hash,
                content_hashes=scoped_content_hashes,
                retrieval_mode="visual_hybrid",
            )
            visual_retrieval_latency_ms = int((time.perf_counter() - start) * 1000)

        retrieved = _enrich_text_documents(retrieved, scope_resolution)
        table_results = _enrich_table_documents(table_results, scope_resolution)
        visual_results = _enrich_visual_documents(visual_results, scope_resolution)
        if is_multi_document_scope:
            retrieved, table_results, visual_results = _limit_context_by_document(
                retrieved=retrieved,
                table_results=table_results,
                visual_results=visual_results,
                top_k=top_k,
                table_top_k=table_top_k,
                visual_top_k=visual_top_k,
                max_documents=max_documents,
                max_evidence_per_document=max_evidence_per_document,
            )
        if table_results:
            table_reasoning = reason_over_table_evidence(
                question=question,
                tables=table_results,
            )
        if visual_results:
            visual_interpretation = self.ai_provider.interpret_visual_evidence(
                question=question,
                visual_evidence=build_visual_evidence_inputs(
                    visual_results,
                    limit=visual_top_k,
                ),
            )

        documents_used = _documents_used(
            scope_resolution=scope_resolution,
            retrieved=retrieved,
            table_results=table_results,
            visual_results=visual_results,
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
            "visual_indexed_collection": self.visual_collection_name,
            "visual_top_k": visual_top_k,
            "visual_retrieval_mode": "visual_hybrid",
            "visual_retrieval_requested": should_retrieve_visuals,
            "visual_retrieval_latency_ms": visual_retrieval_latency_ms,
            "visual_retrieved_count": len(visual_results),
            "visual_intent_detected": visual_intent["detected"],
            "visual_intent_score": visual_intent["score"],
            "visual_intent_matches": visual_intent["matches"],
            "visual_interpretation_status": (
                visual_interpretation.status if visual_interpretation else None
            ),
            "visual_interpretation": visual_interpretation_debug(visual_interpretation),
            "content_hash_scope": "specific" if scoped_content_hashes is not None else "all",
            "scope": scope,
            "documents_searched": [
                document.as_debug() for document in scope_resolution.documents
            ],
            "documents_searched_count": len(scope_resolution.documents),
            "documents_used": [document.as_debug() for document in documents_used],
            "documents_used_count": len(documents_used),
            "max_documents": max_documents,
            "max_evidence_per_document": max_evidence_per_document,
            "candidate_pool_top_k": context_pool_top_k,
            "evidence_by_document": _evidence_by_document(
                retrieved= retrieved,
                table_results=table_results,
                visual_results=visual_results,
            ),
            "answer_prompt_version": ANSWER_PROMPT_VERSION,
        }
        debug.update(vector_search_debug(collection_name=self.collection_name))
        debug.update(rerank_debug)

        if not retrieved and not table_results and not visual_results:
            answer = (
                "I could not find table evidence in the indexed documents to answer this question."
                if evidence_mode == "table"
                else "I could not find visual evidence in the indexed documents to answer this question."
                if evidence_mode == "visual"
                else "I do not have enough evidence from the indexed document to answer."
            )
            debug.update(
                {
                    "abstention_retry_triggered": False,
                    "initial_top_k": top_k,
                    "retry_top_k": None,
                    "initial_answer_was_abstention": False,
                    "retry_answer_was_abstention": None,
                }
            )
            return QueryOutcome(
                answer=answer,
                citations=[],
                table_citations=[],
                visual_citations=[],
                evidence=[],
                table_evidence=[],
                visual_evidence=[],
                unused_evidence=[],
                unused_table_evidence=[],
                unused_visual_evidence=[],
                visual_interpretation=None,
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
        visual_grounding = visual_observations_to_grounding_evidence(visual_interpretation)
        grounding.extend(visual_grounding)

        # --- Initial answer generation ---
        initial_answer_was_abstention = False
        abstention_retry_triggered = False
        retry_top_k: int | None = None
        retry_answer_was_abstention: bool | None = None

        if should_retrieve_visuals and visual_interpretation is not None:
            answer = visual_interpretation.answer
        else:
            answer = self.ai_provider.generate_grounded_answer(
                question=question,
                evidence=grounding,
            )

        # --- Abstention-triggered evidence expansion retry ---
        initial_answer_was_abstention = _is_abstention(answer)
        if (
            initial_answer_was_abstention
            and should_retrieve_text
            and len(retrieved) > 0
            and evidence_mode in {"text", "auto"}
        ):
            retry_top_k = min(top_k * 2, 8)
            retry_retrieved, retry_rerank_debug = self._retrieve_with_optional_rerank(
                question=question,
                content_hash=scoped_content_hash,
                content_hashes=scoped_content_hashes,
                top_k=retry_top_k,
                retrieval_mode=retrieval_mode,
                rerank=rerank_requested,
                rerank_top_n=max(rerank_candidate_top_n, retry_top_k),
            )
            rerank_debug = {
                f"retry_{key}": value
                for key, value in retry_rerank_debug.items()
            }
            abstention_retry_triggered = True
            retry_retrieved = _enrich_text_documents(retry_retrieved, scope_resolution)
            if is_multi_document_scope:
                retry_retrieved, _, _ = _limit_context_by_document(
                    retrieved=retry_retrieved,
                    table_results=[],
                    visual_results=[],
                    top_k=retry_top_k,
                    table_top_k=0,
                    visual_top_k=0,
                    max_documents=max_documents,
                    max_evidence_per_document=max_evidence_per_document,
                )
            retry_grounding = [
                GroundingEvidence(
                    citation_id=f"C{index}",
                    text=chunk.text,
                    source=_format_source(chunk),
                )
                for index, chunk in enumerate(retry_retrieved, start=1)
            ]
            retry_grounding.extend(_table_grounding_evidence(table_results, table_reasoning))
            retry_grounding.extend(visual_grounding)
            answer = self.ai_provider.generate_grounded_answer(
                question=question,
                evidence=retry_grounding,
            )
            retry_answer_was_abstention = _is_abstention(answer)
            retrieved = retry_retrieved
            grounding = retry_grounding

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
            elif (
                citation_verification.verdict == "partially_supported"
                and citation_verification.revised_answer
            ):
                answer = citation_verification.revised_answer

        cited_ids = _extract_citation_ids(answer)
        citations = _build_answer_citations(retrieved, cited_ids)
        table_citations = _build_table_answer_citations(table_results, cited_ids)
        visual_citations = _build_visual_answer_citations(visual_results, cited_ids)
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
        unused_visual_evidence = [
            visual
            for index, visual in enumerate(visual_results, start=1)
            if f"V{index}" not in cited_ids
        ]
        documents_used = _documents_used(
            scope_resolution=scope_resolution,
            retrieved=retrieved,
            table_results=table_results,
            visual_results=visual_results,
        )

        debug.update(
            {
                "answer_citation_count": len(citations),
                "answer_table_citation_count": len(table_citations),
                "answer_visual_citation_count": len(visual_citations),
                "unused_retrieved_count": len(unused_evidence),
                "unused_table_retrieved_count": len(unused_table_evidence),
                "unused_visual_retrieved_count": len(unused_visual_evidence),
                "citation_verification": (
                    asdict(citation_verification)
                    if citation_verification is not None
                    else None
                ),
                "abstention_retry_triggered": abstention_retry_triggered,
                "initial_top_k": top_k,
                "retry_top_k": retry_top_k,
                "initial_answer_was_abstention": initial_answer_was_abstention,
                "retry_answer_was_abstention": retry_answer_was_abstention,
                "documents_used": [document.as_debug() for document in documents_used],
                "documents_used_count": len(documents_used),
                "evidence_by_document": _evidence_by_document(
                    retrieved=retrieved,
                    table_results=table_results,
                    visual_results=visual_results,
                ),
            }
        )
        debug.update(rerank_debug)

        return QueryOutcome(
            answer=answer,
            citations=citations,
            table_citations=table_citations,
            visual_citations=visual_citations,
            evidence=retrieved,
            table_evidence=table_results,
            visual_evidence=visual_results,
            unused_evidence=unused_evidence,
            unused_table_evidence=unused_table_evidence,
            unused_visual_evidence=unused_visual_evidence,
            visual_interpretation=visual_interpretation,
            citation_verification=citation_verification,
            debug=debug,
        )

    def _retrieve(
        self,
        *,
        question: str,
        content_hash: str | None,
        content_hashes: list[str] | None = None,
        top_k: int,
        retrieval_mode: str,
    ) -> list[RetrievedChunk]:
        if retrieval_mode == "dense":
            query_vector = self.ai_provider.embed_texts([question])[0]
            try:
                return search_text_chunks(
                    self.qdrant_client,
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    top_k=top_k,
                    content_hash=content_hash,
                    content_hashes=content_hashes,
                )
            except Exception as exc:
                if _is_missing_vector_collection_error(exc):
                    return []
                raise
        if retrieval_mode == "bm25":
            return self.bm25_retriever.search(
                query=question,
                top_k=top_k,
                content_hash=content_hash,
                content_hashes=content_hashes,
            )
        if retrieval_mode == "hybrid":
            query_vector = self.ai_provider.embed_texts([question])[0]
            try:
                dense_results = search_text_chunks(
                    self.qdrant_client,
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    top_k=max(top_k * 2, top_k),
                    content_hash=content_hash,
                    content_hashes=content_hashes,
                )
            except Exception as exc:
                if _is_missing_vector_collection_error(exc):
                    dense_results = []
                else:
                    raise
            lexical_results = self.bm25_retriever.search(
                query=question,
                top_k=max(top_k * 2, top_k),
                content_hash=content_hash,
                content_hashes=content_hashes,
            )
            return merge_hybrid_results(
                dense_results=dense_results,
                lexical_results=lexical_results,
                top_k=top_k,
            )
        raise ValueError(f"Unsupported retrieval mode: {retrieval_mode}")

    def _retrieve_with_optional_rerank(
        self,
        *,
        question: str,
        content_hash: str | None,
        content_hashes: list[str] | None = None,
        top_k: int,
        retrieval_mode: str,
        rerank: bool,
        rerank_top_n: int,
    ) -> tuple[list[RetrievedChunk], dict]:
        candidate_top_n = max(rerank_top_n, top_k) if rerank else top_k
        candidates = self._retrieve(
            question=question,
            content_hash=content_hash,
            content_hashes=content_hashes,
            top_k=candidate_top_n,
            retrieval_mode=retrieval_mode,
        )
        debug = {
            "rerank_requested": rerank,
            "rerank_used": False,
            "reranker_model": self.reranker_model if rerank else None,
            "reranker_status": "disabled" if not rerank else "no_candidates",
            "rerank_candidate_top_n": candidate_top_n if rerank else None,
            "rerank_candidate_count": len(candidates) if rerank else None,
            "rerank_latency_ms": None,
            "pre_rerank_top_chunk_ids": [chunk.chunk_id for chunk in candidates[:top_k]] if rerank else [],
            "post_rerank_top_chunk_ids": [],
            "rerank_error": None,
        }
        if not rerank:
            return candidates[:top_k], debug
        if not candidates:
            return [], debug

        start = time.perf_counter()
        try:
            reranked = self._get_reranker().rerank(
                question,
                candidates,
                top_k=top_k,
            )
        except RerankerUnavailableError as exc:
            debug.update(
                {
                    "reranker_status": "unavailable",
                    "rerank_error": str(exc),
                    "rerank_latency_ms": int((time.perf_counter() - start) * 1000),
                }
            )
            return candidates[:top_k], debug
        except Exception as exc:
            debug.update(
                {
                    "reranker_status": "failed",
                    "rerank_error": str(exc),
                    "rerank_latency_ms": int((time.perf_counter() - start) * 1000),
                }
            )
            return candidates[:top_k], debug

        debug.update(
            {
                "rerank_used": True,
                "reranker_status": "applied",
                "rerank_latency_ms": int((time.perf_counter() - start) * 1000),
                "post_rerank_top_chunk_ids": [chunk.chunk_id for chunk in reranked],
            }
        )
        return reranked, debug

    def _get_reranker(self) -> object:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker(
                model_name=self.reranker_model,
                device=self.reranker_device,
                batch_size=self.reranker_batch_size,
                max_length=self.reranker_max_length,
            )
        return self._reranker


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
        for match in re.findall(r"\[(C\d+|T\d+|V\d+)\]", answer, flags=re.IGNORECASE)
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
                doc_id=chunk.doc_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                content_hash=chunk.content_hash,
                dense_score=chunk.dense_score,
                lexical_score=chunk.lexical_score,
                hybrid_score=chunk.hybrid_score,
                rerank_score=chunk.rerank_score,
                pre_rerank_rank=chunk.pre_rerank_rank,
                post_rerank_rank=chunk.post_rerank_rank,
                reranker_model=chunk.reranker_model,
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
                doc_id=table.doc_id,
                document_id=table.document_id,
                filename=table.filename,
                content_hash=table.content_hash,
                dense_score=table.dense_score,
                lexical_score=table.lexical_score,
                hybrid_score=table.hybrid_score,
            )
        )
    return citations


def _build_visual_answer_citations(
    visual_results: list[VisualQueryResult],
    cited_ids: set[str],
) -> list[VisualCitation]:
    citations: list[VisualCitation] = []
    for index, visual in enumerate(visual_results, start=1):
        citation_id = f"V{index}"
        if citation_id not in cited_ids:
            continue
        citations.append(
            VisualCitation(
                citation_id=citation_id,
                evidence_type="visual",
                visual_id=visual.visual_id,
                source_path=visual.source_path,
                source_artifact_path=visual.source_artifact_path,
                artifact_path=visual.artifact_path,
                page_start=visual.page_start,
                page_end=visual.page_end,
                visual_type=visual.visual_type,
                visual_readiness=visual.visual_readiness,
                score=visual.score,
                doc_id=visual.doc_id,
                document_id=visual.document_id,
                filename=visual.filename,
                content_hash=visual.content_hash,
                dense_score=visual.dense_score,
                lexical_score=visual.lexical_score,
                hybrid_score=visual.hybrid_score,
            )
        )
    return citations


def _validate_scope_arguments(
    *,
    scope: str,
    content_hash: str | None,
    doc_ids: list[str] | None,
    document_ids: list[str] | None,
    max_documents: int,
    max_evidence_per_document: int,
) -> None:
    if scope not in {"single", "doc_ids", "all"}:
        raise ValueError(f"Unsupported query scope: {scope}")
    if max_documents < 1 or max_documents > 25:
        raise ValueError("max_documents must be between 1 and 25.")
    if max_evidence_per_document < 1 or max_evidence_per_document > 10:
        raise ValueError("max_evidence_per_document must be between 1 and 10.")
    selected_ids = (doc_ids or []) + (document_ids or [])
    if scope == "single":
        if content_hash and selected_ids:
            raise ValueError("scope='single' accepts content_hash or one document identifier, not both.")
        if not content_hash and len(selected_ids) != 1:
            raise ValueError("scope='single' requires content_hash or exactly one doc_id/document_id.")
    elif scope == "doc_ids":
        if content_hash:
            raise ValueError("scope='doc_ids' does not accept content_hash.")
        if not selected_ids:
            raise ValueError("scope='doc_ids' requires doc_ids or document_ids.")
    elif content_hash or selected_ids:
        raise ValueError("scope='all' cannot be combined with document filters.")


def _enrich_text_documents(
    results: list[RetrievedChunk],
    scope_resolution: ScopeResolution,
) -> list[RetrievedChunk]:
    by_content_hash = scope_resolution.by_content_hash
    return [
        replace(
            result,
            document_id=(
                by_content_hash[result.content_hash].document_id
                if result.content_hash in by_content_hash
                else result.document_id
            ),
            doc_id=(
                by_content_hash[result.content_hash].doc_id
                if result.content_hash in by_content_hash
                else result.doc_id
            ),
        )
        for result in results
    ]


def _enrich_table_documents(
    results: list[TableQueryResult],
    scope_resolution: ScopeResolution,
) -> list[TableQueryResult]:
    by_content_hash = scope_resolution.by_content_hash
    return [
        replace(
            result,
            doc_id=(
                by_content_hash[result.content_hash].doc_id
                if result.content_hash in by_content_hash
                else result.doc_id
            ),
        )
        for result in results
    ]


def _enrich_visual_documents(
    results: list[VisualQueryResult],
    scope_resolution: ScopeResolution,
) -> list[VisualQueryResult]:
    by_content_hash = scope_resolution.by_content_hash
    return [
        replace(
            result,
            doc_id=(
                by_content_hash[result.content_hash].doc_id
                if result.content_hash in by_content_hash
                else result.doc_id
            ),
        )
        for result in results
    ]


def _limit_context_by_document(
    *,
    retrieved: list[RetrievedChunk],
    table_results: list[TableQueryResult],
    visual_results: list[VisualQueryResult],
    top_k: int,
    table_top_k: int,
    visual_top_k: int,
    max_documents: int,
    max_evidence_per_document: int,
) -> tuple[list[RetrievedChunk], list[TableQueryResult], list[VisualQueryResult]]:
    candidates: list[tuple[str, str, float, object]] = [
        ("text", result.chunk_id, result.score, result) for result in retrieved
    ]
    candidates.extend(
        ("table", result.table_id, result.score, result) for result in table_results
    )
    candidates.extend(
        ("visual", result.visual_id, result.score, result) for result in visual_results
    )
    candidates.sort(key=lambda candidate: candidate[2], reverse=True)

    retained: dict[str, set[str]] = {"text": set(), "table": set(), "visual": set()}
    kind_limits = {"text": top_k, "table": table_top_k, "visual": visual_top_k}
    document_counts: dict[str, int] = {}
    included_documents: set[str] = set()
    for kind, item_id, _, result in candidates:
        if len(retained[kind]) >= kind_limits[kind]:
            continue
        document_key = _document_key(result)
        if document_key not in included_documents:
            if len(included_documents) >= max_documents:
                continue
            included_documents.add(document_key)
        if document_counts.get(document_key, 0) >= max_evidence_per_document:
            continue
        retained[kind].add(item_id)
        document_counts[document_key] = document_counts.get(document_key, 0) + 1

    return (
        [result for result in retrieved if result.chunk_id in retained["text"]],
        [result for result in table_results if result.table_id in retained["table"]],
        [result for result in visual_results if result.visual_id in retained["visual"]],
    )


def _multi_document_candidate_top_k(
    *,
    scope: str,
    top_k: int,
    table_top_k: int,
    visual_top_k: int,
    max_documents: int,
    max_evidence_per_document: int,
) -> int:
    minimum_pool = 50 if scope == "all" else 20
    requested_context = max(
        top_k,
        table_top_k,
        visual_top_k,
        max_documents * max_evidence_per_document,
    )
    return min(50, max(minimum_pool, requested_context))


def _documents_used(
    *,
    scope_resolution: ScopeResolution,
    retrieved: list[RetrievedChunk],
    table_results: list[TableQueryResult],
    visual_results: list[VisualQueryResult],
) -> list[QueryDocumentRef]:
    by_content_hash = scope_resolution.by_content_hash
    documents: list[QueryDocumentRef] = []
    seen: set[str] = set()
    for result in [*retrieved, *table_results, *visual_results]:
        if result.content_hash in seen:
            continue
        seen.add(result.content_hash)
        document = by_content_hash.get(result.content_hash)
        if document:
            documents.append(document)
            continue
        documents.append(
            QueryDocumentRef(
                doc_id=getattr(result, "doc_id", None),
                document_id=getattr(result, "document_id", None) or "",
                content_hash=result.content_hash,
                filename=result.filename,
                source_path=result.source_path,
            )
        )
    return documents


def _evidence_by_document(
    *,
    retrieved: list[RetrievedChunk],
    table_results: list[TableQueryResult],
    visual_results: list[VisualQueryResult],
) -> list[dict]:
    summaries: dict[str, dict] = {}
    for kind, results in (
        ("text", retrieved),
        ("table", table_results),
        ("visual", visual_results),
    ):
        for result in results:
            summary = summaries.setdefault(
                result.content_hash,
                {
                    "doc_id": getattr(result, "doc_id", None),
                    "document_id": getattr(result, "document_id", None),
                    "filename": result.filename,
                    "content_hash": result.content_hash,
                    "text_count": 0,
                    "table_count": 0,
                    "visual_count": 0,
                },
            )
            summary[f"{kind}_count"] += 1
    return list(summaries.values())


def _document_key(result: object) -> str:
    return str(
        getattr(result, "content_hash", None)
        or getattr(result, "document_id", None)
        or "unknown"
    )


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


def detect_visual_intent(question: str) -> dict:
    normalized = question.lower()
    terms = [
        "figure",
        "fig.",
        "chart",
        "diagram",
        "exhibit",
        "image",
        "graph",
        "plot",
        "visual",
        "shown",
        "illustrates",
        "line",
        "bar",
        "legend",
        "axis",
        "trend",
    ]
    matches = [
        term
        for term in terms
        if re.search(rf"\b{re.escape(term)}s?\b", normalized)
    ]
    explicit = {"figure", "fig.", "chart", "diagram", "exhibit", "image", "graph", "plot", "visual"}
    detected = any(match in explicit for match in matches)
    detected = detected or ("shown" in matches and any(term in normalized for term in ["chart", "figure", "graph"]))
    deduped_matches = list(dict.fromkeys(matches))
    return {
        "detected": detected,
        "score": len(deduped_matches),
        "matches": deduped_matches,
    }
