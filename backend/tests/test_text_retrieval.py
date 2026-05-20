import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docifer_backend.ingestion.models import Document, DocumentIndexRun
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.providers.base import CitationGroundingVerdict, GroundingEvidence
from docifer_backend.retrieval.chunking import build_text_chunks_from_canonical
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.storage.database import Base


class FakeAIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_fake_embedding(text) for text in texts]

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        return f"Countries should use staged growth strategies [{evidence[0].citation_id}]."

    def verify_citation_grounding(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[GroundingEvidence],
    ) -> CitationGroundingVerdict:
        return CitationGroundingVerdict(
            verdict="supported",
            supported_citation_ids=["C1"],
            weak_citation_ids=[],
            unsupported_claims=[],
            reasoning="The answer is supported by C1.",
            revised_answer=None,
        )


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_build_text_chunks_preserves_page_metadata(tmp_path):
    canonical_path, _, _ = write_canonical_artifacts(tmp_path)

    chunks = build_text_chunks_from_canonical(canonical_path, max_chars=180)

    assert chunks
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2
    assert "Middle-income countries" in chunks[0].text
    assert chunks[0].chunk_id.endswith(":text:0000")


def test_text_indexing_is_idempotent(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_canonical_artifacts(tmp_path)
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    service = TextIndexingService(
        session_factory=session_factory,
        ai_provider=FakeAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_text_chunks",
        initialize_schema=False,
    )

    first = service.index_canonical_document(canonical_path)
    second = service.index_canonical_document(canonical_path)

    assert first.status == IngestionStatus.INDEXED.value
    assert first.chunk_count > 0
    assert second.reused_existing is True
    with session_factory() as session:
        chunk_count = session.query(TextChunkRecord).count()
        index_count = session.query(DocumentIndexRun).count()
        assert chunk_count == first.chunk_count
        assert index_count == 1


def test_text_query_returns_answer_citations_and_evidence(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_canonical_artifacts(tmp_path)
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    provider = FakeAIProvider()
    qdrant_client = QdrantClient(":memory:")
    TextIndexingService(
        session_factory=session_factory,
        ai_provider=provider,
        qdrant_client=qdrant_client,
        collection_name="test_text_chunks",
        initialize_schema=False,
    ).index_canonical_document(canonical_path)

    outcome = TextQueryService(
        ai_provider=provider,
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_text_chunks",
    ).query(
        question="What growth strategy should middle-income countries use?",
        content_hash=content_hash,
        top_k=2,
    )

    assert "[C1]" in outcome.answer
    assert outcome.citations[0].citation_id == "C1"
    assert outcome.evidence
    assert outcome.debug["retrieved_count"] > 0
    assert outcome.debug["unused_retrieved_count"] == len(outcome.evidence) - 1


def test_bm25_query_retrieves_lexical_matches(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_canonical_artifacts(tmp_path)
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    provider = FakeAIProvider()
    qdrant_client = QdrantClient(":memory:")
    TextIndexingService(
        session_factory=session_factory,
        ai_provider=provider,
        qdrant_client=qdrant_client,
        collection_name="test_text_chunks",
        initialize_schema=False,
    ).index_canonical_document(canonical_path)

    outcome = TextQueryService(
        ai_provider=provider,
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_text_chunks",
    ).query(
        question="innovation",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="bm25",
    )

    assert outcome.evidence
    assert outcome.evidence[0].retrieval_mode == "bm25"
    assert outcome.evidence[0].lexical_score is not None


def test_hybrid_query_exposes_score_breakdown_and_verifier(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_canonical_artifacts(tmp_path)
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    provider = FakeAIProvider()
    qdrant_client = QdrantClient(":memory:")
    TextIndexingService(
        session_factory=session_factory,
        ai_provider=provider,
        qdrant_client=qdrant_client,
        collection_name="test_text_chunks",
        initialize_schema=False,
    ).index_canonical_document(canonical_path)

    outcome = TextQueryService(
        ai_provider=provider,
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_text_chunks",
    ).query(
        question="middle-income innovation",
        content_hash=content_hash,
        top_k=2,
        retrieval_mode="hybrid",
        verify_citations=True,
    )

    assert outcome.evidence
    assert outcome.evidence[0].retrieval_mode == "hybrid"
    assert outcome.evidence[0].hybrid_score is not None
    assert outcome.citation_verification is not None
    assert outcome.citation_verification.verdict == "supported"


def write_canonical_artifacts(tmp_path: Path) -> tuple[Path, str, str]:
    content_hash = "b" * 64
    source_path = str(tmp_path / "sample.pdf")
    docling_path = tmp_path / "docling.json"
    canonical_path = tmp_path / "canonical.json"

    docling_path.write_text(
        json.dumps(
            {
                "texts": [
                    {
                        "label": "page_header",
                        "text": "Repeated header",
                        "prov": [{"page_no": 1}],
                        "self_ref": "#/texts/0",
                    },
                    {
                        "label": "section_header",
                        "text": "The Middle-Income Trap",
                        "prov": [{"page_no": 1}],
                        "self_ref": "#/texts/1",
                    },
                    {
                        "label": "text",
                        "text": "Middle-income countries need investment and infusion.",
                        "prov": [{"page_no": 1}],
                        "self_ref": "#/texts/2",
                    },
                    {
                        "label": "text",
                        "text": "Upper-middle-income countries add innovation.",
                        "prov": [{"page_no": 2}],
                        "self_ref": "#/texts/3",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps(
            {
                "artifacts": {
                    "docling_json": str(docling_path),
                },
                "document": {
                    "content_hash": content_hash,
                    "filename": "sample.pdf",
                    "source_path": source_path,
                },
            }
        ),
        encoding="utf-8",
    )
    return canonical_path, content_hash, source_path


def _fake_embedding(text: str) -> list[float]:
    lower = text.lower()
    return [
        1.0 if "middle" in lower else 0.0,
        1.0 if "innovation" in lower else 0.0,
        1.0,
    ]
