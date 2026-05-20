from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from docifer_backend.retrieval.chunking import TextChunk


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


def ensure_text_collection(
    client: QdrantClient,
    *,
    collection_name: str,
    vector_size: int,
) -> None:
    if client.collection_exists(collection_name):
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=vector_size,
            distance=models.Distance.COSINE,
        ),
    )


def upsert_text_chunks(
    client: QdrantClient,
    *,
    collection_name: str,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
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
    client.upsert(collection_name=collection_name, points=points, wait=True)


def search_text_chunks(
    client: QdrantClient,
    *,
    collection_name: str,
    query_vector: list[float],
    top_k: int,
    content_hash: str | None = None,
) -> list[RetrievedChunk]:
    query_filter = None
    if content_hash:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="content_hash",
                    match=models.MatchValue(value=content_hash),
                )
            ]
        )

    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
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
            )
        )
    return results
