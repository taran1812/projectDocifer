from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import QdrantClient

from docifer_backend.config.settings import get_settings
from docifer_backend.providers.base import AIProvider, GroundingEvidence
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.vector_store import RetrievedChunk, search_text_chunks
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


@dataclass(frozen=True)
class QueryOutcome:
    answer: str
    citations: list[QueryCitation]
    evidence: list[RetrievedChunk]
    debug: dict


class TextQueryService:
    def __init__(
        self,
        *,
        ai_provider: AIProvider | None = None,
        qdrant_client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.collection_name = collection_name or settings.qdrant_text_collection

    def query(
        self,
        *,
        question: str,
        content_hash: str | None = None,
        top_k: int = 4,
    ) -> QueryOutcome:
        query_vector = self.ai_provider.embed_texts([question])[0]
        retrieved = search_text_chunks(
            self.qdrant_client,
            collection_name=self.collection_name,
            query_vector=query_vector,
            top_k=top_k,
            content_hash=content_hash,
        )

        if not retrieved:
            return QueryOutcome(
                answer="I do not have enough evidence from the indexed document to answer.",
                citations=[],
                evidence=[],
                debug={
                    "collection_name": self.collection_name,
                    "top_k": top_k,
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
        citations = [
            QueryCitation(
                citation_id=item.citation_id,
                chunk_id=chunk.chunk_id,
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=chunk.score,
            )
            for item, chunk in zip(grounding, retrieved, strict=True)
        ]

        return QueryOutcome(
            answer=answer,
            citations=citations,
            evidence=retrieved,
            debug={
                "collection_name": self.collection_name,
                "top_k": top_k,
                "retrieved_count": len(retrieved),
            },
        )


def _format_source(chunk: RetrievedChunk) -> str:
    if chunk.page_start and chunk.page_end and chunk.page_start != chunk.page_end:
        page_label = f"pages {chunk.page_start}-{chunk.page_end}"
    elif chunk.page_start:
        page_label = f"page {chunk.page_start}"
    else:
        page_label = "page unknown"
    return f"{chunk.filename}, {page_label}, chunk {chunk.chunk_id}"
