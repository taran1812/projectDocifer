from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient, QdrantClient, models

from docifer_backend.config.settings import get_settings
from docifer_backend.retrieval.chunking import TextChunk
from docifer_backend.retrieval.tables.schemas import TableEvidence

if TYPE_CHECKING:
    from docifer_backend.retrieval.visuals.schemas import VisualEvidence as VisualEvidenceType


TEXT_PAYLOAD_INDEXES = {
    "content_hash": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "source_path": models.PayloadSchemaType.KEYWORD,
    "page_start": models.PayloadSchemaType.INTEGER,
}

TABLE_PAYLOAD_INDEXES = {
    "content_hash": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "table_type": models.PayloadSchemaType.KEYWORD,
    "table_readiness": models.PayloadSchemaType.KEYWORD,
    "page_start": models.PayloadSchemaType.INTEGER,
}

VISUAL_PAYLOAD_INDEXES = {
    "content_hash": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "visual_type": models.PayloadSchemaType.KEYWORD,
    "source_kind": models.PayloadSchemaType.KEYWORD,
    "page_start": models.PayloadSchemaType.INTEGER,
}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    score: float
    dense_score: float | None
    lexical_score: float | None
    hybrid_score: float | None
    retrieval_mode: str
    text: str
    filename: str
    source_path: str
    source_artifact_path: str
    content_hash: str
    page_start: int | None
    page_end: int | None
    document_id: str | None = None
    doc_id: str | None = None
    rerank_score: float | None = None
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None
    reranker_model: str | None = None


def ensure_text_collection(
    client: QdrantClient,
    *,
    collection_name: str,
    vector_size: int,
) -> None:
    _ensure_collection(
        client,
        collection_name=collection_name,
        vector_size=vector_size,
        payload_indexes=TEXT_PAYLOAD_INDEXES,
    )


def ensure_table_collection(
    client: QdrantClient,
    *,
    collection_name: str,
    vector_size: int,
) -> None:
    _ensure_collection(
        client,
        collection_name=collection_name,
        vector_size=vector_size,
        payload_indexes=TABLE_PAYLOAD_INDEXES,
    )


def upsert_text_chunks(
    client: QdrantClient,
    *,
    collection_name: str,
    document_id: str,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    batch_size: int = 128,
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk and embedding counts must match.")
    if not chunks:
        return

    ensure_text_collection(
        client,
        collection_name=collection_name,
        vector_size=len(embeddings[0]),
    )
    points = [
        models.PointStruct(
            id=chunk.id,
            vector=embedding,
            payload={
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "document_id": document_id,
                "filename": chunk.filename,
                "source_path": chunk.source_path,
                "source_artifact_path": chunk.source_artifact_path,
                "text": chunk.text,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            },
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[start:start + batch_size],
            wait=True,
        )


def upsert_table_evidence(
    client: QdrantClient,
    *,
    collection_name: str,
    tables: list[TableEvidence],
    embeddings: list[list[float]],
    point_ids: list[str],
    batch_size: int = 128,
) -> None:
    if len(tables) != len(embeddings) or len(tables) != len(point_ids):
        raise ValueError("Table, embedding, and point ID counts must match.")
    if not tables:
        return

    ensure_table_collection(
        client,
        collection_name=collection_name,
        vector_size=len(embeddings[0]),
    )
    points = [
        models.PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "table_id": table.table_id,
                "content_hash": table.content_hash,
                "document_id": table.document_id,
                "canonical_path": table.canonical_path,
                "page_start": table.page_start,
                "page_end": table.page_end,
                "table_type": table.table_type,
                "source_kind": table.source_kind,
                "section_heading": table.section_heading,
                "table_readiness": table.table_readiness,
                "evidence_type": "structured table" if table.table_type == "structured" else "table-like text",
                "extraction_method": table.extraction_method,
                "span_hash": table.span_hash,
                "source_chunk_id": table.source_chunk_id,
                "source_path": table.source_path,
                "source_artifact_path": table.source_artifact_path,
            },
        )
        for table, embedding, point_id in zip(tables, embeddings, point_ids, strict=True)
    ]
    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[start:start + batch_size],
            wait=True,
        )


def search_table_evidence_points(
    client: QdrantClient,
    *,
    collection_name: str,
    query_vector: list[float],
    top_k: int,
    content_hash: str | None = None,
    content_hashes: list[str] | None = None,
) -> list[tuple[str, float]]:
    query_filter = _content_hash_filter(content_hash, content_hashes)
    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        search_params=_vector_search_params(),
        limit=top_k,
        with_payload=True,
    )

    results: list[tuple[str, float]] = []
    for point in response.points:
        payload = point.payload or {}
        table_id = payload.get("table_id")
        if table_id:
            results.append((str(table_id), float(point.score)))
    return results


def delete_table_evidence_by_content_hash(
    client: QdrantClient,
    *,
    collection_name: str,
    content_hash: str,
) -> None:
    if not client.collection_exists(collection_name):
        return
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="content_hash",
                        match=models.MatchValue(value=content_hash),
                    )
                ]
            )
        ),
        wait=True,
    )


def search_text_chunks(
    client: QdrantClient,
    *,
    collection_name: str,
    query_vector: list[float],
    top_k: int,
    content_hash: str | None = None,
    content_hashes: list[str] | None = None,
) -> list[RetrievedChunk]:
    query_filter = _content_hash_filter(content_hash, content_hashes)

    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        search_params=_vector_search_params(),
        limit=top_k,
        with_payload=True,
    )

    results: list[RetrievedChunk] = []
    for point in response.points:
        payload = point.payload or {}
        results.append(
            RetrievedChunk(
                chunk_id=str(payload["chunk_id"]),
                score=float(point.score),
                dense_score=float(point.score),
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="dense",
                text=str(payload["text"]),
                filename=str(payload["filename"]),
                source_path=str(payload["source_path"]),
                source_artifact_path=str(payload["source_artifact_path"]),
                content_hash=str(payload["content_hash"]),
                page_start=payload.get("page_start"),
                page_end=payload.get("page_end"),
                document_id=(
                    str(payload["document_id"])
                    if payload.get("document_id") is not None
                    else None
                ),
            )
        )
    return results


async def search_text_chunks_async(
    query: str,
    *,
    client: AsyncQdrantClient,
    collection_name: str,
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    top_k: int = 4,
    content_hash: str | None = None,
    content_hashes: list[str] | None = None,
    exact: bool | None = None,
    ef: int | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    use_exact = exact if exact is not None else settings.qdrant_exact_search
    use_ef = ef if ef is not None else settings.qdrant_search_ef

    embeddings = await embed_fn([query])
    if not embeddings:
        raise ValueError("embed_fn returned no embeddings for query")
    query_vector = embeddings[0]
    search_params = models.SearchParams(
        exact=use_exact,
        hnsw_ef=use_ef if not use_exact else None,
    )
    query_filter = _content_hash_filter(content_hash, content_hashes)

    response = await client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        search_params=search_params,
        with_payload=True,
    )

    results: list[RetrievedChunk] = []
    for point in response.points:
        payload = point.payload or {}
        doc_id_raw = payload.get("document_id")
        results.append(
            RetrievedChunk(
                chunk_id=str(payload.get("chunk_id") or point.id),
                score=float(point.score),
                dense_score=float(point.score),
                lexical_score=None,
                hybrid_score=None,
                retrieval_mode="dense",
                text=str(payload["text"]),
                filename=str(payload.get("filename") or ""),
                source_path=str(payload["source_path"]),
                source_artifact_path=str(payload["source_artifact_path"]),
                content_hash=str(payload["content_hash"]),
                page_start=payload.get("page_start"),
                page_end=payload.get("page_end"),
                document_id=str(doc_id_raw) if doc_id_raw is not None else None,
            )
        )
    return results


def _content_hash_filter(
    content_hash: str | None,
    content_hashes: list[str] | None = None,
) -> models.Filter | None:
    selected_hashes = content_hashes if content_hashes is not None else (
        [content_hash] if content_hash else None
    )
    if selected_hashes is None:
        return None
    if not selected_hashes:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="content_hash",
                    match=models.MatchAny(any=[]),
                )
            ]
        )
    match = (
        models.MatchValue(value=selected_hashes[0])
        if len(selected_hashes) == 1
        else models.MatchAny(any=selected_hashes)
    )
    return models.Filter(
        must=[
            models.FieldCondition(
                key="content_hash",
                match=match,
            )
        ]
    )


def ensure_visual_collection(
    client: QdrantClient,
    *,
    collection_name: str,
    vector_size: int,
) -> None:
    _ensure_collection(
        client,
        collection_name=collection_name,
        vector_size=vector_size,
        payload_indexes=VISUAL_PAYLOAD_INDEXES,
    )


def upsert_visual_evidence(
    client: QdrantClient,
    *,
    collection_name: str,
    visuals: list[VisualEvidenceType],
    embeddings: list[list[float]],
    point_ids: list[str],
    batch_size: int = 128,
) -> None:
    if len(visuals) != len(embeddings) or len(visuals) != len(point_ids):
        raise ValueError("Visual, embedding, and point ID counts must match.")
    if not visuals:
        return

    ensure_visual_collection(
        client,
        collection_name=collection_name,
        vector_size=len(embeddings[0]),
    )
    points = [
        models.PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "visual_id": visual.visual_id,
                "content_hash": visual.content_hash,
                "document_id": visual.document_id,
                "canonical_path": visual.canonical_path,
                "page_start": visual.page_start,
                "page_end": visual.page_end,
                "visual_type": visual.visual_type,
                "source_kind": visual.source_kind,
                "artifact_path": visual.artifact_path,
                "caption": visual.caption,
                "section_heading": visual.section_heading,
                "figure_label": visual.figure_label,
                "visual_readiness": visual.visual_readiness,
                "extraction_method": visual.extraction_method,
                "source_path": visual.source_path,
                "source_artifact_path": visual.source_artifact_path,
            },
        )
        for visual, embedding, point_id in zip(visuals, embeddings, point_ids, strict=True)
    ]
    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[start : start + batch_size],
            wait=True,
        )


def search_visual_evidence_points(
    client: QdrantClient,
    *,
    collection_name: str,
    query_vector: list[float],
    top_k: int,
    content_hash: str | None = None,
    content_hashes: list[str] | None = None,
) -> list[tuple[str, float]]:
    query_filter = _content_hash_filter(content_hash, content_hashes)
    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        search_params=_vector_search_params(),
        limit=top_k,
        with_payload=True,
    )
    results: list[tuple[str, float]] = []
    for point in response.points:
        payload = point.payload or {}
        visual_id = payload.get("visual_id")
        if visual_id:
            results.append((str(visual_id), float(point.score)))
    return results


def delete_visual_evidence_by_content_hash(
    client: QdrantClient,
    *,
    collection_name: str,
    content_hash: str,
) -> None:
    if not client.collection_exists(collection_name):
        return
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="content_hash",
                        match=models.MatchValue(value=content_hash),
                    )
                ]
            )
        ),
        wait=True,
    )


def vector_search_debug(*, collection_name: str) -> dict:
    settings = get_settings()
    return {
        "vector_search_exact": settings.qdrant_exact_search,
        "vector_search_ef": settings.qdrant_search_ef,
        "vector_collection": collection_name,
    }


def _ensure_collection(
    client: QdrantClient,
    *,
    collection_name: str,
    vector_size: int,
    payload_indexes: dict[str, models.PayloadSchemaType],
) -> None:
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
            hnsw_config=_hnsw_config(),
        )
    if get_settings().qdrant_create_payload_indexes:
        ensure_payload_indexes(
            client,
            collection_name=collection_name,
            payload_indexes=payload_indexes,
        )


def ensure_payload_indexes(
    client: QdrantClient,
    *,
    collection_name: str,
    payload_indexes: dict[str, models.PayloadSchemaType],
) -> None:
    for field_name, field_schema in payload_indexes.items():
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )
        except Exception as exc:
            message = str(exc).lower()
            if "already" in message or "exists" in message:
                continue
            raise


def _vector_search_params() -> models.SearchParams:
    settings = get_settings()
    return models.SearchParams(
        exact=settings.qdrant_exact_search,
        hnsw_ef=settings.qdrant_search_ef,
    )


def _hnsw_config() -> models.HnswConfigDiff:
    settings = get_settings()
    return models.HnswConfigDiff(
        m=settings.qdrant_hnsw_m,
        ef_construct=settings.qdrant_hnsw_ef_construct,
    )
