from __future__ import annotations

from docifer_backend.retrieval.vector_store import RetrievedChunk


def merge_hybrid_results(
    *,
    dense_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    top_k: int,
    dense_weight: float = 0.6,
    lexical_weight: float = 0.4,
) -> list[RetrievedChunk]:
    dense_norm = _normalize_scores({chunk.chunk_id: chunk.score for chunk in dense_results})
    lexical_norm = _normalize_scores({chunk.chunk_id: chunk.score for chunk in lexical_results})
    by_chunk_id: dict[str, RetrievedChunk] = {}
    for chunk in dense_results + lexical_results:
        by_chunk_id[chunk.chunk_id] = chunk

    merged: list[RetrievedChunk] = []
    for chunk_id, chunk in by_chunk_id.items():
        dense_score = dense_norm.get(chunk_id, 0.0)
        lexical_score = lexical_norm.get(chunk_id, 0.0)
        hybrid_score = (dense_weight * dense_score) + (lexical_weight * lexical_score)
        merged.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                score=hybrid_score,
                dense_score=dense_score if chunk_id in dense_norm else None,
                lexical_score=lexical_score if chunk_id in lexical_norm else None,
                hybrid_score=hybrid_score,
                retrieval_mode="hybrid",
                text=chunk.text,
                filename=chunk.filename,
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                content_hash=chunk.content_hash,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                document_id=chunk.document_id,
                doc_id=chunk.doc_id,
            )
        )

    merged.sort(key=lambda chunk: chunk.score, reverse=True)
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
