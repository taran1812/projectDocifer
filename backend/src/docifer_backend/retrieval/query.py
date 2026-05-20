from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from qdrant_client import QdrantClient

from docifer_backend.config.settings import get_settings
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.providers.base import AIProvider, CitationGroundingVerdict, GroundingEvidence
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.bm25 import BM25Retriever
from docifer_backend.retrieval.hybrid import merge_hybrid_results
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
    evidence: list[RetrievedChunk]
    unused_evidence: list[RetrievedChunk]
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
    ) -> None:
        settings = get_settings()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.session_factory = session_factory or get_session_factory()
        self.collection_name = collection_name or settings.qdrant_text_collection
        self.bm25_retriever = BM25Retriever(session_factory=self.session_factory)

    def query(
        self,
        *,
        question: str,
        content_hash: str | None = None,
        top_k: int = 4,
        retrieval_mode: str = "dense",
        verify_citations: bool = False,
    ) -> QueryOutcome:
        retrieval_mode = retrieval_mode.lower()
        retrieved = self._retrieve(
            question=question,
            content_hash=content_hash,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )

        if not retrieved:
            return QueryOutcome(
                answer="I do not have enough evidence from the indexed document to answer.",
                citations=[],
                evidence=[],
                unused_evidence=[],
                citation_verification=None,
                debug={
                    "collection_name": self.collection_name,
                    "top_k": top_k,
                    "retrieval_mode": retrieval_mode,
                    "retrieved_count": 0,
                },
            )

        grounding = [
            GroundingEvidence(
                citation_id=f"C{index}",
                text=chunk.text,
                source=_format_source(chunk),
            )
            for index, chunk in enumerate(retrieved, start=1)
        ]
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
        unused_evidence = [
            chunk
            for index, chunk in enumerate(retrieved, start=1)
            if f"C{index}" not in cited_ids
        ]

        return QueryOutcome(
            answer=answer,
            citations=citations,
            evidence=retrieved,
            unused_evidence=unused_evidence,
            citation_verification=citation_verification,
            debug={
                "collection_name": self.collection_name,
                "top_k": top_k,
                "retrieval_mode": retrieval_mode,
                "verify_citations": verify_citations,
                "retrieved_count": len(retrieved),
                "answer_citation_count": len(citations),
                "unused_retrieved_count": len(unused_evidence),
                "citation_verification": (
                    asdict(citation_verification)
                    if citation_verification is not None
                    else None
                ),
            },
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


def _extract_citation_ids(answer: str) -> set[str]:
    return {match.upper() for match in re.findall(r"\[(C\d+)\]", answer, flags=re.IGNORECASE)}


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
