from types import MethodType

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docifer_backend.providers.base import CitationGroundingVerdict, GroundingEvidence
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.retrieval.reranking import FakeReranker
from docifer_backend.retrieval.vector_store import RetrievedChunk
from docifer_backend.schemas.retrieval import QueryRequest
from docifer_backend.storage.database import Base


class FakeAIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 1.0] for _ in texts]

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        return f"Answer from {evidence[0].citation_id}."

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
            reasoning="Supported.",
            revised_answer=None,
        )


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_fake_reranker_preserves_top_k_and_changes_order():
    evidence = _chunks(4)
    reranker = FakeReranker(
        scores_by_chunk_id={
            "chunk-4": 9.0,
            "chunk-2": 8.0,
            "chunk-1": 1.0,
            "chunk-3": 0.5,
        }
    )

    reranked = reranker.rerank("question", evidence, top_k=2)

    assert [chunk.chunk_id for chunk in reranked] == ["chunk-4", "chunk-2"]
    assert len(reranked) == 2
    assert reranked[0].rerank_score == 9.0
    assert reranked[0].pre_rerank_rank == 4
    assert reranked[0].post_rerank_rank == 1
    assert reranked[0].reranker_model == "fake-reranker"


def test_query_rerank_false_preserves_existing_top_k(session_factory):
    service = _service(session_factory, reranker=FakeReranker())
    calls: list[int] = []
    _stub_retrieve(service, calls=calls, evidence=_chunks(5))

    outcome = service.query(
        question="What is the answer?",
        top_k=2,
        retrieval_mode="hybrid",
        evidence_mode="text",
        rerank=False,
    )

    assert calls == [2]
    assert [chunk.chunk_id for chunk in outcome.evidence] == ["chunk-1", "chunk-2"]
    assert outcome.debug["rerank_used"] is False
    assert outcome.debug["reranker_status"] == "disabled"
    assert service._reranker.calls == []


def test_query_rerank_true_retrieves_candidates_and_returns_final_top_k(session_factory):
    reranker = FakeReranker(
        scores_by_chunk_id={
            "chunk-4": 10.0,
            "chunk-2": 8.0,
            "chunk-1": 1.0,
            "chunk-3": 0.5,
        }
    )
    service = _service(session_factory, reranker=reranker)
    calls: list[int] = []
    _stub_retrieve(service, calls=calls, evidence=_chunks(5))

    outcome = service.query(
        question="What is the answer?",
        top_k=2,
        retrieval_mode="hybrid",
        evidence_mode="text",
        rerank=True,
        rerank_top_n=4,
    )

    assert calls == [4]
    assert [chunk.chunk_id for chunk in outcome.evidence] == ["chunk-4", "chunk-2"]
    assert outcome.debug["rerank_used"] is True
    assert outcome.debug["reranker_status"] == "applied"
    assert outcome.debug["rerank_candidate_count"] == 4
    assert outcome.debug["pre_rerank_top_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert outcome.debug["post_rerank_top_chunk_ids"] == ["chunk-4", "chunk-2"]
    assert outcome.evidence[0].rerank_score == 10.0


def test_query_reranker_failure_falls_back_to_original_order(session_factory):
    service = _service(session_factory, reranker=FakeReranker(fail=True))
    calls: list[int] = []
    _stub_retrieve(service, calls=calls, evidence=_chunks(5))

    outcome = service.query(
        question="What is the answer?",
        top_k=2,
        retrieval_mode="hybrid",
        evidence_mode="text",
        rerank=True,
        rerank_top_n=4,
    )

    assert calls == [4]
    assert [chunk.chunk_id for chunk in outcome.evidence] == ["chunk-1", "chunk-2"]
    assert outcome.debug["rerank_used"] is False
    assert outcome.debug["reranker_status"] == "failed"
    assert "fake reranker failed" in outcome.debug["rerank_error"]


def test_query_rejects_rerank_top_n_smaller_than_top_k(session_factory):
    service = _service(session_factory, reranker=FakeReranker())

    with pytest.raises(ValueError, match="rerank_top_n"):
        service.query(
            question="What is the answer?",
            top_k=4,
            retrieval_mode="hybrid",
            evidence_mode="text",
            rerank=True,
            rerank_top_n=3,
        )


def test_query_request_rejects_rerank_top_n_smaller_than_top_k():
    with pytest.raises(ValueError, match="rerank_top_n"):
        QueryRequest(
            question="What is the answer?",
            top_k=4,
            rerank=True,
            rerank_top_n=3,
        )


def _service(session_factory, *, reranker):
    return TextQueryService(
        ai_provider=FakeAIProvider(),
        qdrant_client=QdrantClient(":memory:"),
        session_factory=session_factory,
        collection_name="test_text_chunks",
        reranker=reranker,
    )


def _stub_retrieve(service: TextQueryService, *, calls: list[int], evidence: list[RetrievedChunk]) -> None:
    def fake_retrieve(self, *, question, content_hash, top_k, retrieval_mode):
        calls.append(top_k)
        return evidence[:top_k]

    service._retrieve = MethodType(fake_retrieve, service)


def _chunks(count: int) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{index}",
            score=float(count - index),
            dense_score=float(count - index),
            lexical_score=None,
            hybrid_score=float(count - index),
            retrieval_mode="hybrid",
            text=f"Evidence text {index}",
            filename="sample.pdf",
            source_path="datasets/raw_pdfs/sample.pdf",
            source_artifact_path="datasets/processed/sample/canonical.json",
            content_hash="a" * 64,
            page_start=index,
            page_end=index,
        )
        for index in range(1, count + 1)
    ]
