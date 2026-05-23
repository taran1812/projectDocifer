from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.vector_store import RetrievedChunk
from docifer_backend.storage.database import get_session_factory


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class BM25Document:
    chunk: TextChunkRecord
    token_counts: Counter[str]
    token_count: int


class BM25Retriever:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.k1 = k1
        self.b = b

    def search(
        self,
        *,
        query: str,
        top_k: int,
        content_hash: str | None = None,
        content_hashes: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        documents = self._load_documents(
            content_hash=content_hash,
            content_hashes=content_hashes,
        )
        if not documents:
            return []

        avg_doc_len = sum(document.token_count for document in documents) / len(documents)
        document_frequency = _document_frequency(documents)
        scored: list[tuple[float, TextChunkRecord]] = []
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
            if score > 0:
                scored.append((score, document.chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                score=score,
                dense_score=None,
                lexical_score=score,
                hybrid_score=None,
                retrieval_mode="bm25",
                text=chunk.text,
                filename=chunk.source_path.split("\\")[-1].split("/")[-1],
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                content_hash=chunk.content_hash,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                document_id=chunk.document_id,
            )
            for score, chunk in scored[:top_k]
        ]

    def _load_documents(
        self,
        *,
        content_hash: str | None,
        content_hashes: list[str] | None = None,
    ) -> list[BM25Document]:
        with self.session_factory() as session:
            statement = select(TextChunkRecord)
            if content_hashes is not None:
                statement = statement.where(TextChunkRecord.content_hash.in_(content_hashes))
            elif content_hash:
                statement = statement.where(TextChunkRecord.content_hash == content_hash)
            chunks = session.scalars(statement.order_by(TextChunkRecord.chunk_index)).all()

        documents: list[BM25Document] = []
        for chunk in chunks:
            tokens = tokenize(chunk.text)
            if not tokens:
                continue
            documents.append(
                BM25Document(
                    chunk=chunk,
                    token_counts=Counter(tokens),
                    token_count=len(tokens),
                )
            )
        return documents


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def _document_frequency(documents: list[BM25Document]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for document in documents:
        for term in document.token_counts:
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies
