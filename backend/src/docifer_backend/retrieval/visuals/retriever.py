from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.settings import get_settings
from docifer_backend.providers.base import AIProvider
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.bm25 import tokenize
from docifer_backend.retrieval.vector_store import (
    _content_hash_filter,
    _vector_search_params,
    search_visual_evidence_points,
)
from docifer_backend.retrieval.visuals.models import VisualEvidenceRecord
from docifer_backend.retrieval.visuals.schemas import VisualQueryResult
from docifer_backend.storage.database import get_session_factory
from docifer_backend.storage.qdrant import get_async_qdrant_client, get_qdrant_client


@dataclass(frozen=True)
class _BM25VisualDocument:
    record: VisualEvidenceRecord
    text: str
    token_counts: Counter[str]
    token_count: int


class VisualRetriever:
    def __init__(
        self,
        *,
        ai_provider: AIProvider | None = None,
        qdrant_client: QdrantClient | None = None,
        session_factory: sessionmaker[Session] | None = None,
        collection_name: str | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        settings = get_settings()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.session_factory = session_factory or get_session_factory()
        self.collection_name = collection_name or settings.qdrant_visual_collection
        self.k1 = k1
        self.b = b

    def search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None = None,
        content_hashes: list[str] | None = None,
        retrieval_mode: str = "visual_hybrid",
    ) -> list[VisualQueryResult]:
        mode = retrieval_mode.lower()
        if mode == "visual_dense":
            return self._dense_search(query=query, top_k=top_k, content_hash=content_hash, content_hashes=content_hashes)
        if mode == "visual_bm25":
            return self._bm25_search(query=query, top_k=top_k, content_hash=content_hash, content_hashes=content_hashes)
        if mode == "visual_hybrid":
            dense = self._dense_search(query=query, top_k=max(top_k * 2, top_k), content_hash=content_hash, content_hashes=content_hashes)
            lexical = self._bm25_search(query=query, top_k=max(top_k * 2, top_k), content_hash=content_hash, content_hashes=content_hashes)
            return _merge_hybrid(dense_results=dense, lexical_results=lexical, top_k=top_k)
        raise ValueError(f"Unsupported visual retrieval mode: {retrieval_mode}")

    async def search_async(
        self,
        query: str,
        *,
        top_k: int = 4,
        content_hash: str | None = None,
        content_hashes: list[str] | None = None,
    ) -> list[VisualQueryResult]:
        async_client = get_async_qdrant_client()
        query_vector = (await self.ai_provider.embed_texts_async([query]))[0]
        query_filter = _content_hash_filter(content_hash, content_hashes)
        try:
            response = await async_client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                search_params=_vector_search_params(),
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            return []
        scored_points: list[tuple[str, float]] = []
        for point in response.points:
            payload = point.payload or {}
            visual_id = payload.get("visual_id")
            if visual_id:
                scored_points.append((str(visual_id), float(point.score)))
        if not scored_points:
            return []
        records = self._load_records_by_visual_ids(
            visual_ids=[vid for vid, _ in scored_points],
            content_hash=content_hash,
            content_hashes=content_hashes,
        )
        by_id = {record.visual_id: record for record in records}
        results = [
            _record_to_result(
                by_id[vid],
                score=score,
                dense_score=score,
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="visual_dense",
            )
            for vid, score in scored_points
            if vid in by_id
        ]
        return results[:top_k]

    def _dense_search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[VisualQueryResult]:
        query_vector = self.ai_provider.embed_texts([query])[0]
        try:
            scored_points = search_visual_evidence_points(
                self.qdrant_client,
                collection_name=self.collection_name,
                query_vector=query_vector,
                top_k=top_k,
                content_hash=content_hash,
                content_hashes=content_hashes,
            )
        except (UnexpectedResponse, ValueError):
            return []
        if not scored_points:
            return []
        records = self._load_records_by_visual_ids(
            visual_ids=[vid for vid, _ in scored_points],
            content_hash=content_hash,
            content_hashes=content_hashes,
        )
        by_id = {r.visual_id: r for r in records}
        return [
            _record_to_result(
                by_id[vid],
                score=score,
                dense_score=score,
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="visual_dense",
            )
            for vid, score in scored_points
            if vid in by_id
        ][:top_k]

    def _bm25_search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[VisualQueryResult]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        documents = self._load_bm25_documents(content_hash=content_hash, content_hashes=content_hashes)
        if not documents:
            return []

        avg_len = sum(d.token_count for d in documents) / len(documents)
        df = _document_frequency(documents)
        scored: list[tuple[float, VisualEvidenceRecord]] = []
        for doc in documents:
            score = 0.0
            for term in query_terms:
                tf = doc.token_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log(
                    1 + ((len(documents) - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
                )
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * (doc.token_count / avg_len))
                score += idf * (numerator / denominator)
            if score > 0:
                scored.append((score, doc.record))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            _record_to_result(
                record,
                score=score,
                dense_score=None,
                lexical_score=score,
                hybrid_score=None,
                retrieval_mode="visual_bm25",
            )
            for score, record in scored[:top_k]
        ]

    def _load_records_by_visual_ids(
        self,
        *,
        visual_ids: list[str],
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[VisualEvidenceRecord]:
        with self.session_factory() as session:
            stmt = (
                select(VisualEvidenceRecord)
                .where(VisualEvidenceRecord.visual_id.in_(visual_ids))
                .where(VisualEvidenceRecord.qdrant_point_id.is_not(None))
            )
            if content_hashes is not None:
                stmt = stmt.where(VisualEvidenceRecord.content_hash.in_(content_hashes))
            elif content_hash:
                stmt = stmt.where(VisualEvidenceRecord.content_hash == content_hash)
            return list(session.scalars(stmt))

    def _load_bm25_documents(
        self,
        *,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[_BM25VisualDocument]:
        with self.session_factory() as session:
            stmt = select(VisualEvidenceRecord).where(VisualEvidenceRecord.qdrant_point_id.is_not(None))
            if content_hashes is not None:
                stmt = stmt.where(VisualEvidenceRecord.content_hash.in_(content_hashes))
            elif content_hash:
                stmt = stmt.where(VisualEvidenceRecord.content_hash == content_hash)
            records = list(session.scalars(stmt.order_by(VisualEvidenceRecord.visual_index)))

        documents: list[_BM25VisualDocument] = []
        for record in records:
            text = _bm25_text(record)
            tokens = tokenize(text)
            if not tokens:
                continue
            documents.append(
                _BM25VisualDocument(
                    record=record,
                    text=text,
                    token_counts=Counter(tokens),
                    token_count=len(tokens),
                )
            )
        return documents


def _record_to_result(
    record: VisualEvidenceRecord,
    *,
    score: float,
    dense_score: float | None,
    lexical_score: float | None,
    hybrid_score: float | None,
    retrieval_mode: str,
) -> VisualQueryResult:
    return VisualQueryResult(
        visual_id=record.visual_id,
        score=score,
        dense_score=dense_score,
        lexical_score=lexical_score,
        hybrid_score=hybrid_score,
        retrieval_mode=retrieval_mode,
        visual_type=record.visual_type,
        source_kind=record.source_kind,
        page_start=record.page_start,
        page_end=record.page_end,
        artifact_path=record.artifact_path,
        caption=record.caption,
        section_heading=record.section_heading,
        nearby_text=record.nearby_text,
        figure_label=record.figure_label,
        visual_readiness=record.visual_readiness,
        document_id=record.document_id,
        content_hash=record.content_hash,
        filename=record.filename,
        source_path=record.source_path,
        source_artifact_path=record.source_artifact_path,
    )


def _bm25_text(record: VisualEvidenceRecord) -> str:
    parts = [
        record.caption,
        record.figure_label,
        record.section_heading,
        record.nearby_text,
        record.filename,
    ]
    return "\n".join(p for p in parts if p)


def _merge_hybrid(
    *,
    dense_results: list[VisualQueryResult],
    lexical_results: list[VisualQueryResult],
    top_k: int,
    dense_weight: float = 0.35,
    lexical_weight: float = 0.65,
) -> list[VisualQueryResult]:
    dense_norm = _normalize({r.visual_id: r.score for r in dense_results})
    lexical_norm = _normalize({r.visual_id: r.score for r in lexical_results})
    by_id: dict[str, VisualQueryResult] = {}
    for r in dense_results + lexical_results:
        by_id[r.visual_id] = r

    merged: list[VisualQueryResult] = []
    for vid, result in by_id.items():
        ds = dense_norm.get(vid, 0.0)
        ls = lexical_norm.get(vid, 0.0)
        hs = dense_weight * ds + lexical_weight * ls
        merged.append(VisualQueryResult(
            visual_id=result.visual_id,
            score=hs,
            dense_score=ds if vid in dense_norm else None,
            lexical_score=ls if vid in lexical_norm else None,
            hybrid_score=hs,
            retrieval_mode="visual_hybrid",
            visual_type=result.visual_type,
            source_kind=result.source_kind,
            page_start=result.page_start,
            page_end=result.page_end,
            artifact_path=result.artifact_path,
            caption=result.caption,
            section_heading=result.section_heading,
            nearby_text=result.nearby_text,
            figure_label=result.figure_label,
            visual_readiness=result.visual_readiness,
            document_id=result.document_id,
            content_hash=result.content_hash,
            filename=result.filename,
            source_path=result.source_path,
            source_artifact_path=result.source_artifact_path,
            doc_id=result.doc_id,
        ))
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged[:top_k]


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    max_s = max(scores.values())
    min_s = min(scores.values())
    if max_s == min_s:
        return {k: 1.0 for k in scores}
    return {k: (v - min_s) / (max_s - min_s) for k, v in scores.items()}


def _document_frequency(documents: list[_BM25VisualDocument]) -> dict[str, int]:
    df: dict[str, int] = {}
    for doc in documents:
        for term in doc.token_counts:
            df[term] = df.get(term, 0) + 1
    return df
