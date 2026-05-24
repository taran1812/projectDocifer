from __future__ import annotations

import math
import re
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
from docifer_backend.retrieval.tables.models import TableEvidenceRecord
from docifer_backend.retrieval.tables.schemas import TableQueryResult
from docifer_backend.retrieval.vector_store import (
    _content_hash_filter,
    _vector_search_params,
    search_table_evidence_points,
)
from docifer_backend.storage.database import get_session_factory
from docifer_backend.storage.qdrant import get_async_qdrant_client, get_qdrant_client


BOOST_TERMS = [
    "net income",
    "net interest income",
    "noninterest revenue",
    "revenue",
    "segment",
    "assets",
    "liabilities",
    "highest",
    "lowest",
    "compare",
    "total",
]


@dataclass(frozen=True)
class _BM25TableDocument:
    record: TableEvidenceRecord
    text: str
    token_counts: Counter[str]
    token_count: int


class TableRetriever:
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
        self.collection_name = collection_name or settings.qdrant_table_collection
        self.k1 = k1
        self.b = b

    def search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None = None,
        content_hashes: list[str] | None = None,
        retrieval_mode: str = "table_hybrid",
    ) -> list[TableQueryResult]:
        retrieval_mode = retrieval_mode.lower()
        if retrieval_mode == "table_dense":
            return self._dense_search(query=query, top_k=top_k, content_hash=content_hash, content_hashes=content_hashes)
        if retrieval_mode == "table_bm25":
            return self._bm25_search(query=query, top_k=top_k, content_hash=content_hash, content_hashes=content_hashes)
        if retrieval_mode == "table_hybrid":
            dense_results = self._dense_search(query=query, top_k=max(top_k * 2, top_k), content_hash=content_hash, content_hashes=content_hashes)
            lexical_results = self._bm25_search(query=query, top_k=max(top_k * 2, top_k), content_hash=content_hash, content_hashes=content_hashes)
            return _merge_table_hybrid_results(
                dense_results=dense_results,
                lexical_results=lexical_results,
                top_k=top_k,
            )
        raise ValueError(f"Unsupported table retrieval mode: {retrieval_mode}")

    async def search_async(
        self,
        query: str,
        *,
        top_k: int = 4,
        content_hash: str | None = None,
        content_hashes: list[str] | None = None,
    ) -> list[TableQueryResult]:
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
            table_id = payload.get("table_id")
            if table_id:
                scored_points.append((str(table_id), float(point.score)))
        if not scored_points:
            return []
        records = self._load_records_by_table_ids(
            table_ids=[table_id for table_id, _ in scored_points],
            content_hash=content_hash,
            content_hashes=content_hashes,
        )
        by_table_id = {record.table_id: record for record in records}
        results = [
            _record_to_result(
                by_table_id[table_id],
                score=score,
                dense_score=score,
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="table_dense",
            )
            for table_id, score in scored_points
            if table_id in by_table_id
        ]
        return results[:top_k]

    def _dense_search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[TableQueryResult]:
        query_vector = self.ai_provider.embed_texts([query])[0]
        try:
            scored_points = search_table_evidence_points(
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
        score_by_table_id = dict(scored_points)
        records = self._load_records_by_table_ids(
            table_ids=[table_id for table_id, _ in scored_points],
            content_hash=content_hash,
            content_hashes=content_hashes,
        )
        by_table_id = {record.table_id: record for record in records}
        results = [
            _record_to_result(
                by_table_id[table_id],
                score=score,
                dense_score=score,
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="table_dense",
            )
            for table_id, score in scored_points
            if table_id in by_table_id and table_id in score_by_table_id
        ]
        return results[:top_k]

    def _bm25_search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[TableQueryResult]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        documents = self._load_bm25_documents(content_hash=content_hash, content_hashes=content_hashes)
        if not documents:
            return []

        avg_doc_len = sum(document.token_count for document in documents) / len(documents)
        document_frequency = _document_frequency(documents)
        scored: list[tuple[float, TableEvidenceRecord]] = []
        for document in documents:
            score = 0.0
            for term in query_terms:
                term_frequency = document.token_counts.get(term, 0)
                if term_frequency == 0:
                    continue
                idf = math.log(
                    1
                    + (
                        (len(documents) - document_frequency.get(term, 0) + 0.5)
                        / (document_frequency.get(term, 0) + 0.5)
                    )
                )
                numerator = term_frequency * (self.k1 + 1)
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * (document.token_count / avg_doc_len)
                )
                score += idf * (numerator / denominator)
            score += _table_boost(query, document.record)
            if score > 0:
                scored.append((score, document.record))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            _record_to_result(
                record,
                score=score,
                dense_score=None,
                lexical_score=score,
                hybrid_score=None,
                retrieval_mode="table_bm25",
            )
            for score, record in scored[:top_k]
        ]

    def _load_records_by_table_ids(
        self,
        *,
        table_ids: list[str],
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[TableEvidenceRecord]:
        with self.session_factory() as session:
            statement = (
                select(TableEvidenceRecord)
                .where(TableEvidenceRecord.table_id.in_(table_ids))
                .where(TableEvidenceRecord.qdrant_point_id.is_not(None))
            )
            if content_hashes is not None:
                statement = statement.where(TableEvidenceRecord.content_hash.in_(content_hashes))
            elif content_hash:
                statement = statement.where(TableEvidenceRecord.content_hash == content_hash)
            return list(session.scalars(statement))

    def _load_bm25_documents(
        self,
        *,
        content_hash: str | None,
        content_hashes: list[str] | None,
    ) -> list[_BM25TableDocument]:
        with self.session_factory() as session:
            statement = select(TableEvidenceRecord).where(TableEvidenceRecord.qdrant_point_id.is_not(None))
            if content_hashes is not None:
                statement = statement.where(TableEvidenceRecord.content_hash.in_(content_hashes))
            elif content_hash:
                statement = statement.where(TableEvidenceRecord.content_hash == content_hash)
            records = session.scalars(statement.order_by(TableEvidenceRecord.table_index)).all()

        documents: list[_BM25TableDocument] = []
        for record in records:
            text = _bm25_text(record)
            tokens = tokenize(text)
            if not tokens:
                continue
            documents.append(
                _BM25TableDocument(
                    record=record,
                    text=text,
                    token_counts=Counter(tokens),
                    token_count=len(tokens),
                )
            )
        return documents


def _record_to_result(
    record: TableEvidenceRecord,
    *,
    score: float,
    dense_score: float | None,
    lexical_score: float | None,
    hybrid_score: float | None,
    retrieval_mode: str,
) -> TableQueryResult:
    return TableQueryResult(
        table_id=record.table_id,
        score=score,
        dense_score=dense_score,
        lexical_score=lexical_score,
        hybrid_score=hybrid_score,
        retrieval_mode=retrieval_mode,
        table_type=record.table_type,
        source_kind=record.source_kind,
        page_start=record.page_start,
        page_end=record.page_end,
        raw_text=record.raw_text,
        markdown_table=record.markdown_table,
        structured_json=record.structured_json,
        section_heading=record.section_heading,
        table_readiness=record.table_readiness,
        document_id=record.document_id,
        content_hash=record.content_hash,
        filename=record.filename,
        source_path=record.source_path,
        source_artifact_path=record.source_artifact_path,
        source_chunk_id=record.source_chunk_id,
        title=record.title,
        caption=record.caption,
    )


def _bm25_text(record: TableEvidenceRecord) -> str:
    parts = [
        record.title,
        record.caption,
        record.section_heading,
        record.raw_text,
        record.markdown_table,
        _structured_text(record.structured_json),
    ]
    return "\n".join(part for part in parts if part)


def _structured_text(structured_json: dict | None) -> str | None:
    if not structured_json:
        return None
    headers = structured_json.get("headers") or []
    rows = structured_json.get("rows") or []
    lines = [" ".join(str(header) for header in headers)] if headers else []
    lines.extend(" ".join(str(cell) for cell in row) for row in rows)
    return "\n".join(lines)


def _table_boost(query: str, record: TableEvidenceRecord) -> float:
    query_lower = query.lower()
    record_text = _bm25_text(record).lower()
    boost = 0.0
    for year in set(re.findall(r"\b20\d\d\b", query_lower)):
        if year in record_text:
            boost += 2.0
    for term in BOOST_TERMS:
        if term in query_lower and term in record_text:
            boost += 1.5
    if "segment" in query_lower and any(
        segment_name in record_text
        for segment_name in (
            "commercial & investment bank",
            "consumer & community banking",
            "asset & wealth management",
            "productivity and business processes",
            "intelligent cloud",
            "more personal computing",
        )
    ):
        boost += 3.0
    for token in tokenize(query_lower):
        if len(token) >= 4 and record.section_heading and token in record.section_heading.lower():
            boost += 0.5
    return boost


def _merge_table_hybrid_results(
    *,
    dense_results: list[TableQueryResult],
    lexical_results: list[TableQueryResult],
    top_k: int,
    dense_weight: float = 0.35,
    lexical_weight: float = 0.65,
) -> list[TableQueryResult]:
    dense_norm = _normalize_scores({result.table_id: result.score for result in dense_results})
    lexical_norm = _normalize_scores({result.table_id: result.score for result in lexical_results})
    by_table_id: dict[str, TableQueryResult] = {}
    for result in dense_results + lexical_results:
        by_table_id[result.table_id] = result

    merged: list[TableQueryResult] = []
    for table_id, result in by_table_id.items():
        dense_score = dense_norm.get(table_id, 0.0)
        lexical_score = lexical_norm.get(table_id, 0.0)
        hybrid_score = (dense_weight * dense_score) + (lexical_weight * lexical_score)
        merged.append(
            TableQueryResult(
                table_id=result.table_id,
                score=hybrid_score,
                dense_score=dense_score if table_id in dense_norm else None,
                lexical_score=lexical_score if table_id in lexical_norm else None,
                hybrid_score=hybrid_score,
                retrieval_mode="table_hybrid",
                table_type=result.table_type,
                source_kind=result.source_kind,
                page_start=result.page_start,
                page_end=result.page_end,
                raw_text=result.raw_text,
                markdown_table=result.markdown_table,
                structured_json=result.structured_json,
                section_heading=result.section_heading,
                table_readiness=result.table_readiness,
                document_id=result.document_id,
                content_hash=result.content_hash,
                filename=result.filename,
                source_path=result.source_path,
                source_artifact_path=result.source_artifact_path,
                source_chunk_id=result.source_chunk_id,
                title=result.title,
                caption=result.caption,
                doc_id=result.doc_id,
            )
        )
    merged.sort(key=lambda result: result.score, reverse=True)
    return merged[:top_k]


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    max_score = max(scores.values())
    min_score = min(scores.values())
    if max_score == min_score:
        return {key: 1.0 for key in scores}
    return {
        key: (value - min_score) / (max_score - min_score)
        for key, value in scores.items()
    }


def _document_frequency(documents: list[_BM25TableDocument]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for document in documents:
        for term in document.token_counts:
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies
